/* In-database equivalent (SQL Server 2017+). Cleans a varchar column into a DECIMAL column, logs every correction,
   and asserts before/after row counts match. Schedule: SQL Agent job step  EXEC dbo.usp_CleanNumeric 'dbo.RawSales','amount'; */
CREATE OR ALTER FUNCTION dbo.fn_ParseNumber(@s NVARCHAR(100)) RETURNS DECIMAL(19,4) AS
BEGIN
  DECLARE @t NVARCHAR(100) = LTRIM(RTRIM(REPLACE(@s, NCHAR(160), ''))), @neg BIT = 0;
  IF @t LIKE '(%)' SELECT @neg = 1, @t = SUBSTRING(@t, 2, LEN(@t) - 2);
  IF @t LIKE '%-' AND LEN(@t) > 1 SELECT @neg = 1, @t = LEFT(@t, LEN(@t) - 1);
  -- keep only digits , . - e
  DECLARE @o NVARCHAR(100) = N'', @i INT = 1, @c NCHAR(1);
  WHILE @i <= LEN(@t) BEGIN SET @c = SUBSTRING(@t, @i, 1); IF @c LIKE N'[0-9.,-]' SET @o += @c; SET @i += 1; END;
  -- decide decimal separator: whichever of , . appears last; a single comma not followed by exactly 3 digits = decimal
  IF CHARINDEX(',', @o) > 0 AND CHARINDEX('.', @o) > 0
     SET @o = CASE WHEN LEN(@o) - CHARINDEX(',', REVERSE(@o)) > LEN(@o) - CHARINDEX('.', REVERSE(@o))
                   THEN REPLACE(REPLACE(@o, '.', ''), ',', '.') ELSE REPLACE(@o, ',', '') END;
  ELSE IF LEN(@o) - LEN(REPLACE(@o, ',', '')) = 1 AND CHARINDEX(',', REVERSE(@o)) - 1 <> 3 SET @o = REPLACE(@o, ',', '.');
  ELSE SET @o = REPLACE(@o, ',', '');
  DECLARE @v DECIMAL(19,4) = TRY_CONVERT(DECIMAL(19,4), @o);
  RETURN CASE WHEN @neg = 1 THEN -ABS(@v) ELSE @v END;
END;
GO
IF OBJECT_ID('dbo.CleanLog') IS NULL
  CREATE TABLE dbo.CleanLog(id INT IDENTITY PRIMARY KEY, run_at DATETIME2 DEFAULT SYSDATETIME(), table_name SYSNAME, column_name SYSNAME, row_key NVARCHAR(100), old_value NVARCHAR(100), new_value DECIMAL(19,4), action VARCHAR(10));
GO
CREATE OR ALTER PROCEDURE dbo.usp_CleanNumeric @table SYSNAME, @column SYSNAME, @key SYSNAME = 'id' AS
BEGIN
  SET NOCOUNT ON; SET XACT_ABORT ON;
  DECLARE @sql NVARCHAR(MAX), @before INT, @after INT, @clean SYSNAME = @column + '_clean';
  SET @sql = N'SELECT @n = COUNT(*) FROM ' + @table; EXEC sp_executesql @sql, N'@n INT OUT', @before OUT;
  BEGIN TRAN;
  IF COL_LENGTH(@table, @clean) IS NULL BEGIN SET @sql = N'ALTER TABLE ' + @table + ' ADD ' + QUOTENAME(@clean) + ' DECIMAL(19,4) NULL'; EXEC (@sql); END;
  SET @sql = N'
    INSERT dbo.CleanLog(table_name, column_name, row_key, old_value, new_value, action)
    SELECT @t, @c, CAST(' + QUOTENAME(@key) + ' AS NVARCHAR(100)), ' + QUOTENAME(@column) + ', dbo.fn_ParseNumber(' + QUOTENAME(@column) + '),
           CASE WHEN dbo.fn_ParseNumber(' + QUOTENAME(@column) + ') IS NULL THEN ''invalid'' ELSE ''fixed'' END
    FROM ' + @table + ' WHERE TRY_CONVERT(DECIMAL(19,4), ' + QUOTENAME(@column) + ') IS NULL
       OR CAST(TRY_CONVERT(DECIMAL(19,4), ' + QUOTENAME(@column) + ') AS NVARCHAR(100)) <> LTRIM(RTRIM(' + QUOTENAME(@column) + '));
    UPDATE ' + @table + ' SET ' + QUOTENAME(@clean) + ' = dbo.fn_ParseNumber(' + QUOTENAME(@column) + ');
    SELECT @n = COUNT(*) FROM ' + @table + ';';
  EXEC sp_executesql @sql, N'@t SYSNAME, @c SYSNAME, @n INT OUT', @table, @column, @after OUT;
  IF @before <> @after BEGIN ROLLBACK; THROW 50001, 'Row count mismatch – rolled back', 1; END;
  COMMIT;
  SELECT @before AS rows_before, @after AS rows_after, (SELECT COUNT(*) FROM dbo.CleanLog WHERE table_name = @table AND run_at >= DATEADD(MINUTE,-1,SYSDATETIME())) AS logged_corrections;
END;
GO
/* sample:
CREATE TABLE dbo.RawSales(id INT PRIMARY KEY, amount NVARCHAR(50));
INSERT dbo.RawSales VALUES (1,'1200.50'),(2,'1,450.00'),(3,'  99 '),(4,'(250.00)'),(5,'1.234,56'),(6,'12O');
EXEC dbo.usp_CleanNumeric 'dbo.RawSales','amount';  */
