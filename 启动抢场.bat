@echo off
chcp 65001 >nul
cd /d "C:\Users\86188\Documents\badminton"
echo [%date% %time%] 脚本启动 >> run.log
C:\Users\86188\AppData\Local\Programs\Python\Python314\python.exe -X utf8 main.py >> run.log 2>&1
echo [%date% %time%] 脚本退出 >> run.log
pause