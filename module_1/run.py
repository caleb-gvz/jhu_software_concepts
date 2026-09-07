from app import create_app

app = create_app()

if __name__ == "__main__":
    # SHALL run at port 8080, host set to 0.0.0.0 so it's reachable
    # at both localhost and your machine's network address.
    app.run(host="0.0.0.0", port=8080, debug=True)
