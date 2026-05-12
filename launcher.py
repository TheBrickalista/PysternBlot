# PyInstaller entry point — avoids relative import issue with __main__.py
from pysternblot.main import main

if __name__ == "__main__":
    main()
