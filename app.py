"""Retry of app, but calling upon jncep directly"""
import logging
import os
import shutil
import sys
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from flask import Flask, send_file, render_template, request
from jncep.cli.epub import generate_epub
from loguru import logger
from waitress import serve

app = Flask(__name__)


def create_epub(jnc_url, part_spec):
    """Create an epub file from a J-Novel Club URL and part specifier"""
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M_%f')
    output_dirpath = f"{os.environ['JNCEP_OUTPUT']}/{request.remote_addr}/{timestamp}"
    Path.mkdir(Path(output_dirpath), parents=True, exist_ok=True)
    logger.info(f"Generating epub(s) at {output_dirpath}")
    # Pass input to jncep per https://github.com/pallets/click/issues/40#issuecomment-326014129
    generate_epub.callback(jnc_url, args["email"], args["password"], part_spec, output_dirpath,
                           args["is_by_volume"], args["is_extract_images"],
                           args["is_extract_content"], args["is_not_replace_chars"],
                           args["style_css_path"])
    logger.info("Epub(s) generated")
    return output_dirpath


def make_one_bytesio_file(directory):
    """Reads directory, returns the file path and name if only one file.
    If multiple files, zips them into a BytesIO object and returns this with the series name"""
    # Path glob doesn't support len as it is a generator, so it needs to be turned into a list
    files = list(Path(directory).glob('*.epub'))
    if len(list(files)) == 1:
        # Single file, but read into a BytesIO object so the actual file can be deleted
        with open(files[0], "rb") as file:
            memory_file = BytesIO(file.read())
        return memory_file, files[0].name
    # Multiple files. Zipping them together, so they can be sent
    logger.info(f"There are {len(list(files))} files. Zipping them together.")
    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in files:
            zipf.write(file, arcname=file.name)
    memory_file.seek(0)  # Return to start of file. 'Re-wind the tape'.
    # Get index of '_Volume_' and use this to get the filename up to read the series title.
    return memory_file, f"{files[0].stem[:files[0].stem.index('_Volume_')]}.zip"


@app.route('/')
def homepage():
    """Load homepage"""
    logger.debug(f"Requesting IP: {request.remote_addr}")
    logger.debug("Requested homepage")
    return render_template('Homepage.html')


@app.route('/', methods=['POST'])
def index():
    """User requested an ebook, process request and return their ebook as a download"""
    logger.info(f"Prepub parts requested by client: {request.remote_addr}")
    logger.debug(f"Requested JNC URL: {request.form['jnovelclub_url']}")
    if request.form.get("prepub_parts"):
        logger.info(f"Requested parts: {request.form['prepub_parts']}")
    else:
        logger.info("Requested ALL")

    # Create the epub and store the save path
    epub_path = create_epub(request.form['jnovelclub_url'], request.form['prepub_parts'])

    # If multiple files, zip them up
    file_object, filename = make_one_bytesio_file(epub_path)

    # Delete the file directory, the file to be sent is a BytesIO object.
    logger.debug("Deleting epub(s)")
    shutil.rmtree(Path(epub_path).parent, ignore_errors=True)

    logger.info("Sending requested epub(s)")
    return send_file(file_object, download_name=filename, as_attachment=True)


class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


if __name__ == "__main__":
    logger.remove()
    logging.basicConfig(handlers=[InterceptHandler()], level=0)
    logger.add(sys.stderr, colorize=True,
               format="<level>{time:YYYY-MM-DD at HH:mm:ss} [{level}]</level> - {message}",
               level="DEBUG")
    logger.add("logs/jncep.log", level="DEBUG",
               format="{time:YYYY-MM-DD at HH:mm:ss} | {level} | {message}",
               rotation="50 MB", compression="zip", retention="1 week")
    # Clear trio RuntimeWarning: "custom sys.excepthook handler installed".
    # This is an issue with Click and out of our control
    os.system('cls')
    logger.info("JNCEP server starting")

    args = {"email": os.environ['JNCEP_EMAIL'], "password": os.environ['JNCEP_PASSWORD'],
            "is_by_volume": True, "is_extract_images": False, "is_extract_content": False,
            "is_not_replace_chars": False, "style_css_path": False}

    serve(app, host="0.0.0.0", port=5000)