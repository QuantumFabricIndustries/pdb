@echo off
REM PDB — push this folder to GitHub (uses your normal Windows GitHub login).
REM First create an EMPTY public repo named "pdb" at https://github.com/organizations/QuantumFabricIndustries/repositories/new
cd /d "%~dp0"
git remote remove origin 2>nul
git remote add origin https://github.com/QuantumFabricIndustries/pdb.git
git branch -M main
git push -u origin main
echo.
echo If you see "main -> main" above, it worked. Next: add the 2 secrets and turn on Pages (see SETUP.txt).
pause
