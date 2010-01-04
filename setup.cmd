@echo off
echo @echo off > %1
echo setlocal >> %1
echo path %2 >> %1
echo %3 %%* >> %1
echo endlocal >> %1
