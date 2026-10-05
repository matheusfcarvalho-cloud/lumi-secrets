"""Route all /api/* requests through the existing WSGI application."""

from server import app as application, init_db


def app(environ, start_response):
    # Each cold function instance prepares its own module state once.
    init_db()
    return application(environ, start_response)
