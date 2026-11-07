"""Точка входа для сборки exe"""
import sys
from server import serve
if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(serve())
