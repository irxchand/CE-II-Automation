import logging
import sys
from rich.logging import RichHandler

def get_logger(name: str = "automation"):
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('[%(module)s]: %(message)s')
        file_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(module)s]: %(message)s')
        
        # File handler
        file_handler = logging.FileHandler('execution.log', encoding='utf-8')
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter('[%(asctime)s] %(levelname)-7s: %(message)s', '%H:%M:%S')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
    return logger

logger = get_logger()
