@echo off
setlocal enabledelayedexpansion

set INIT_SQL=db\init.sql
set IDX_SQL=db\20_indexes.sql

echo == Checking containers ==
docker compose ps

echo.
echo == Current tables ==
docker compose exec db psql -U inv -d inventory -c "\dt"

if exist "%INIT_SQL%" (
  echo.
  echo Applying %INIT_SQL% ...
  type "%INIT_SQL%" | docker compose exec -T db psql -U inv -d inventory -v ON_ERROR_STOP=1 -f -
) else (
  echo Skipping %INIT_SQL% (not found)
)

if exist "%IDX_SQL%" (
  echo.
  echo Applying %IDX_SQL% ...
  type "%IDX_SQL%" | docker compose exec -T db psql -U inv -d inventory -v ON_ERROR_STOP=1 -f -
) else (
  echo Skipping %IDX_SQL% (not found)
)

echo.
echo == Tables after apply ==
docker compose exec db psql -U inv -d inventory -c "\dt"

echo.
echo Done.
endlocal
