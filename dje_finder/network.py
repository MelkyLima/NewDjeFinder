import requests
from pathlib import Path
from dje_finder.config import Config, thread_local
from dje_finder.persistence import is_valid_pdf_file

class PDFDiscovery:
    @staticmethod
    def get_session():
        if not hasattr(thread_local, "session"):
            session = requests.Session()
            session.headers.update({"User-Agent": Config.USER_AGENT})
            thread_local.session = session
        return thread_local.session

    @staticmethod
    def check_and_stream(date_str):
        url = Config.BASE_URL.format(date_str)
        try:
            response = PDFDiscovery.get_session().get(
                url,
                stream=True,
                timeout=Config.REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                return response
            elif response.status_code == 404:
                response.close()
                return None
            else:
                response.raise_for_status()
        except requests.RequestException as error:
            return error

class DownloadManager:
    @staticmethod
    def is_valid_pdf_file(path):
        return is_valid_pdf_file(path)

    @staticmethod
    def is_downloaded(date_str):
        year = date_str[:4]
        path = Config.BASE_DIR / year / f"dpj-{date_str}.pdf"
        return is_valid_pdf_file(path)

    @staticmethod
    def save_pdf(response, date_str, progress_callback=None, limiter=None):
        try:
            year = date_str[:4]
            target_dir = Config.BASE_DIR / year
            target_dir.mkdir(parents=True, exist_ok=True)
            file_path = target_dir / f"dpj-{date_str}.pdf"
            partial_path = file_path.with_suffix(".pdf.part")
            
            with open(partial_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        if limiter:
                            limiter.consume(len(chunk))
                        f.write(chunk)
                        if progress_callback:
                            progress_callback(len(chunk))
            with open(partial_path, "rb") as file:
                is_valid_pdf = file.read(4) == b"%PDF"
            if not is_valid_pdf:
                partial_path.unlink(missing_ok=True)
                raise ValueError("A resposta recebida não contém um arquivo PDF válido.")
            partial_path.replace(file_path)
            return True
        except (OSError, requests.RequestException, ValueError) as error:
            return error
        finally:
            response.close()
