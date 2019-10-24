import os
import requests
import json
import re
from datetime import datetime

from pyciiml.utils.file_utils import read_json

from flask import (
    Flask, request, abort, jsonify, make_response,
    send_from_directory, url_for, redirect, render_template
)
from werkzeug.utils import secure_filename
from http import HTTPStatus
from string import punctuation
import nltk
from nltk import word_tokenize
nltk.download('punkt')


ROOT_URL = '/'
SHARE_FOLDER = 'shared-files'
SHARE_FOLDER_LIST_URL = '/download'
SHARE_FOLDER_DOWNLOAD_BASE_URL = SHARE_FOLDER_LIST_URL + '/'
SHARE_FOLDER_UPLOAD_URL = '/upload'
MED_TERMINOLOGY_FIND_CODE = '/find_codes'
GET_MED_TERMINOLOGIES = '/get_terminologies'
DEFAULT_ALLOWED_EXTENSIONS = (
    'txt', 'rtf', 'doc', 'docx', 'xls', 'xlsx', 'pdf', 'mp4', 'zip',
)


if not os.path.exists(SHARE_FOLDER):
    os.makedirs(SHARE_FOLDER)

# Directories
BASE_DIR = os.path.dirname(__file__)
MED_EMBEDDINGS_PATH = os.path.join(BASE_DIR, 'models', 'med_embeddings_dict.json')
MED_TERMINOLOGY_PATH = os.path.join(BASE_DIR, 'models', 'med_processed_terminologies.json')


med_embeddings = set(read_json(MED_EMBEDDINGS_PATH))
med_processed_terminologies = read_json(MED_TERMINOLOGY_PATH)

stop_words = {
    "/", "-", ",", "(", ")", "[", "]", "upper", "left", "right", "down", "lower", "region",
    "with", "w", "without", "wo", "w/wo", "contrast", "about", "again", "against", "ain't", "all",
    "am", "an", "and", "any", "are", "n't", "aren't", "as", "at", "be", "because", "been", "being", "but",
    "by", "can", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "during",
    "each", "for", "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he's",
    "her", "here", "hers", "herself", "him", "himself", "his", "how", "if", "in", "is", "isn't", "it",
    "it's", "its", "itself", "just", "'ll", "i'll", "you'll", "he'll", "she'll", "they'll", "i'm", "'m", "me",
    "might", "mightn't", "must", "more", "most", "mustn't", "my", "myself", "needn't", "need", "no", "nor", "not",
    "now", "of", "on", "only", "or", "other", "our", "ours", "ourselves", "own", "same", "shan't", "she",
    "she's", "she'd", "he'd", "should", "should've", "shouldn't", "so", "some", "such", "than", "that",
    "that'll", "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they", "this", "those",
    "through", "to", "too", "i've", "very", "was", "wasn't", "we", "we've", "were", "weren't", "what", "when",
    "where", "which", "while", "who", "whom", "why", "will", "with", "wo", "won't", "would", "wouldn't", "y", "you",
    "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves", "i'd", "they'd",
    "top", "middle", "bottom", '``', "''", "•", "date", "time",
}

suppress_words_patterns = [
    r'\s?\d{1,2}/\d{1,2}/\d{2,4}\s?',
    r'(january|jan|february|feb|march|mar|april|apr|may|june|jun)\s+\d{1,2},\s?\d{2,4}\s?',
    r'(july|jul|august|aug|september|sep|october|oct|november|nov|december|dec)\s+\d{1,2},\s?\d{2,4}\s?'
    r'\s?\d{1,2}:\d{1,2}\s\bpm\b|\bPM\b|\bam\b|\bAM\b\s+',
    r'\s?\d{1,2}:\d{1,2}\s+',
    r'\s+\d+\s+day[s]?',
    r'\s+\d{3,}',
    r'</sub>', r'<sub>',
    r'</sup>', r'<sup>',
    r'<', r'>', r'\^',
]
suppress_words = r'|'.join(map(r'(?:{})'.format, suppress_words_patterns))

replace_words = r'/|\\n'


def preprocess_text_for_med_embedding(text, filter_stop_words=True):
    """Preprocess text."""
    lower_text = text.lower()
    suppressed_text = re.sub(suppress_words, '', lower_text)
    replaced_text = re.sub(replace_words, ' ', suppressed_text)
    if filter_stop_words:
        tokens = [token for token in word_tokenize(replaced_text)
                  if token not in punctuation and token not in stop_words]
    else:
        tokens = [token for token in word_tokenize(replaced_text)
                  if token not in punctuation]

    return tokens


class UploadFolderException(Exception):
    pass


class UploadFolderManager(object):
    def __init__(self, upload_folder=SHARE_FOLDER, allowed_extensions=None):
        if allowed_extensions is None:
            allowed_extensions = DEFAULT_ALLOWED_EXTENSIONS
        self.upload_folder = upload_folder
        self.allowed_extensions = allowed_extensions

    def get_extension(self, filename):
        ext = os.path.splitext(filename)[1]
        if ext.startswith('.'):
            ext = ext[1:]
        return ext.lower()

    def get_file_names_in_folder(self):
        return os.listdir(self.upload_folder)

    def validate_filename(self, filename):
        ext = self.get_extension(filename)
        if ext not in self.allowed_extensions:
            if ext == '':
                ext = 'No extension'
            raise UploadFolderException(
                '{ext} file not allowed'.format(ext=ext)
            )
        if '/' in filename:
            raise UploadFolderException(
                'no subdirectories directories allowed'
            )
        if filename in self.get_file_names_in_folder():
            raise UploadFolderException(
                '{filename} exists'.format(filename=filename)
            )
        return ext

    def save_uploaded_file_from_api(self, filename, file_data):
        new_filename = secure_filename(filename)
        self.validate_filename(new_filename)
        with open(os.path.join(self.upload_folder, new_filename), 'wb') as fp:
            fp.write(file_data)
        return '{filename} uploaded'.format(filename=new_filename)

    def save_uploaded_file_from_form(self, file):
        if file is None:
            raise UploadFolderException(
                'No file found'
            )
        filename = secure_filename(file.filename)
        self.validate_filename(filename)
        file.save(os.path.join(self.upload_folder, filename))
        return '{filename} uploaded'.format(filename=filename)

    def get_upload_folder(self):
        return self.upload_folder


api = Flask(__name__)
api.shared_folder_manager = UploadFolderManager(SHARE_FOLDER)


@api.route(ROOT_URL)
@api.route('/index.html', methods=['GET', 'POST'])
def hello_world():
    return render_template('index.html')


@api.route(SHARE_FOLDER_LIST_URL)
def list_files():
    """Endpoint to list files on the server."""
    files = []
    base_url = request.url_root[:-1]
    for filename in api.shared_folder_manager.get_file_names_in_folder():
        path = os.path.join(api.shared_folder_manager.upload_folder, filename)
        if os.path.isfile(path):
            files.append({
                'filename': filename,
                'url': base_url + url_for('.get_file', filename=filename)
            })
    return make_response(jsonify(files)), 200


@api.route(SHARE_FOLDER_DOWNLOAD_BASE_URL + '<string:filename>')
def get_file(filename):
    """Download a file as a attachment."""
    return send_from_directory(
        api.shared_folder_manager.get_upload_folder(),
        filename,
        as_attachment=True
    )


@api.route(SHARE_FOLDER_UPLOAD_URL + '/<string:filename>', methods=['POST'])
def upload_file(filename):
    """Upload a file with api."""
    try:
        result = api.shared_folder_manager.save_uploaded_file_from_api(
            filename, request.data
        )
        # Return 201 CREATED
        return result, 201
    except UploadFolderException as e:
        abort(400, str(e))


@api.route(GET_MED_TERMINOLOGIES, methods=['POST'])
def api_get_terminologies():
    """get med-embedding terminologies"""
    if request.method == 'POST':
        context = request.json['context']
        preprocessed_context = set(preprocess_text_for_med_embedding(context))
        key_tokens = preprocessed_context.intersection(med_embeddings)
        response = {
            "key_tokens": " ".join(key_tokens),
            "message": HTTPStatus.OK.phrase,
            "status-code": HTTPStatus.OK,
            "method": request.method,
            "timestamp": datetime.now().isoformat(),
            "url": request.url,
        }

        return make_response(jsonify(response), response["status-code"])


@api.route(MED_TERMINOLOGY_FIND_CODE, methods=['POST'])
def api_find_code():
    """find code from med-embedding terminology service"""
    if request.method == 'POST':
        endpoint_url = "https://api.dev.ciitizen.net/medembed/find_codes"
        # endpoint_url = "http://localhost:3000/medembed/find_codes"
        r = requests.post(endpoint_url, json=request.json)
        if r.status_code == 200:
            response = json.loads(r.content)
            for result in response['results']:
                concept_key = ' '.join(preprocess_text_for_med_embedding(result['synonym']))
                result_dict = med_processed_terminologies.get(concept_key, (result['code'], "REVIEWED", result['synonym']))
                result['terminology'] = result_dict[1]
                result['synonym'] = result_dict[2]
        else:
            response = {
                "message": "Error on get med-embedding terminology",
                "status-code": r.status_code,
                "method": request.method,
                "timestamp": datetime.now().isoformat(),
                "url": request.url,
            }

        return make_response(jsonify(response), response["status-code"])


@api.route(SHARE_FOLDER_UPLOAD_URL, methods=['POST', 'GET'])
def upload_file_from_form():
    """Upload a file from form."""
    if request.method == 'POST':
        try:
            file = request.files['file']
            api.shared_folder_manager.save_uploaded_file_from_form(file)
            return redirect(url_for('list_files'))
        except UploadFolderException as e:
            upload_url = (
                request.url_root[:-1] + url_for('.upload_file_from_form')
            )
            return """
            <!doctype html>
            <title>Upload file error</title>
            <h1>Upload file error</h1>
            <p>{error}</p>
            <a href={upload_url}>Try again</a>
            """.format(
                error=str(e), upload_url=upload_url
            )
    return """
    <!doctype html>
    <title>Upload new File</title>
    <h1>Upload new File</h1>
    <form action="" method=post enctype=multipart/form-data>
      <p><input type=file name=file>
         <input type=submit value=Upload></p>
    </form>
    <p>%s</p>
    """ % "<br>".join(api.shared_folder_manager.get_file_names_in_folder())


if __name__ == '__main__':
    api.run(host='0.0.0.0', port=5000)
