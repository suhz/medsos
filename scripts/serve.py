"""Run the Flask service. Production: use a real WSGI server (gunicorn)."""
from medsos.web.app import create_app

if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=8768, debug=False)