Module 1 - Personal Portfolio Flask App
=========================================

REQUIREMENTS
------------
Python 3.10 or higher. Check your version with:
    python --version

SETUP
-----
1. Create a virtual environment:

   Windows (PowerShell):
       python -m venv venv
       venv\Scripts\Activate.ps1

   Mac/Linux:
       python3 -m venv venv
       source venv/bin/activate

2. Install dependencies:
       pip install -r requirements.txt

RUNNING THE SITE
----------------
       python run.py

Then open a browser to:
       http://localhost:8080

PROJECT STRUCTURE
------------------
run.py                   - entry point; starts the app on port 8080
app/__init__.py          - Flask application factory
app/routes.py            - Blueprint defining Home, Contact, and Projects routes
app/templates/base.html  - shared layout + navigation bar
app/templates/*.html     - individual page content
app/static/css/style.css - styling for nav bar and page layout
app/static/images/       - place your profile picture here (profile.jpg)

NOTES
-----
- Replace the [bracketed placeholder] text in the templates with your own
  name, position, bio, contact info, and Module 1 project details.
- Add your own photo to app/static/images/profile.jpg.
