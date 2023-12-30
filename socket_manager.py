from flask_socketio import SocketIO, emit, send

socket = SocketIO(cors_allowed_origins='*')

def init_socket(app):
    socket.init_app(app)

def emit(event, data):
    socket.emit(event, data)

# You can add more socket-related functions as needed
