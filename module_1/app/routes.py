from flask import Blueprint, render_template

# Using a Blueprint (rather than routes directly on `app`) keeps page
# logic organized and separate from app setup/config.
main = Blueprint("main", __name__)


@main.route("/")
def home():
    # active_page tells base.html which nav link to highlight
    return render_template("home.html", active_page="home")


@main.route("/contact")
def contact():
    return render_template("contact.html", active_page="contact")


@main.route("/projects")
def projects():
    return render_template("projects.html", active_page="projects")
