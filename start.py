from src.api import Server
from src.core.initialize import initialize

if __name__ == "__main__":
    initialize()
    Server.run()
