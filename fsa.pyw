import concurrent.futures as futures
import json
import os
import re
import threading
import tkinter as tk
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from time import time
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import requests


MAX_RECORDS_IN_XML = 500
CONCLUSION_VALID = 1
CONCLUSION_INVALID = 2
MIN_PROTOCOL_ID = 100000
VERSION = "v1.7"
REQUEST_TIMEOUT = 30
TOKEN_PATTERN = re.compile(
    r"^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Metrologist:
    last_name: str
    first_name: str
    snils: str

    @property
    def full_name(self) -> str:
        return f"{self.last_name} {self.first_name}"


@dataclass(frozen=True)
class VerificationRecord:
    number_verification: str
    date_verification: str
    date_end_verification: Optional[str]
    type_measuring_instrument: str
    result_verification: int
    cancelled: bool = False


@dataclass(frozen=True)
class ReportData:
    records: list[VerificationRecord]
    total_records: int
    skipped_records: int
    cancelled_records: int
    failed_requests: int


def parse_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d.%m.%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def safe_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_token(path: str = "token.txt") -> str:
    try:
        token = open(path, "r", encoding="utf-8").read().strip()
    except OSError as exc:
        raise ValueError(f"Не удалось прочитать {path}: {exc}") from exc

    if not TOKEN_PATTERN.match(token or ""):
        raise ValueError("Токен не найден или имеет некорректный формат")
    return token


def load_metrologists(path: str = "metrologists.json") -> list[Metrologist]:
    try:
        payload = json.load(open(path, "r", encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Не удалось прочитать {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Некорректный JSON в {path}: {exc}") from exc

    items = payload.get("metrologists")
    if not isinstance(items, list) or not items:
        raise ValueError("Файл metrologists.json пустой или имеет неверную структуру")

    result = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Некорректные данные в metrologists.json")
        try:
            result.append(
                Metrologist(
                    last_name=str(item["LastName"]).strip(),
                    first_name=str(item["FirstName"]).strip(),
                    snils=str(item["SNILS"]).strip(),
                )
            )
        except KeyError as exc:
            raise ValueError(f"В metrologists.json отсутствует поле {exc.args[0]}") from exc
    return result


class RestAPI:
    BASE_URL = "https://fgis.gost.ru/fundmetrology/cm/"

    def __init__(self, token: str, timeout: int = REQUEST_TIMEOUT):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def _get(self, path: str) -> Optional[str]:
        try:
            response = self.session.get(f"{self.BASE_URL}{path}", timeout=self.timeout)
            response.raise_for_status()
            return response.text.replace("gost:", "")
        except requests.RequestException:
            return None

    def get_report(self, protocol_id: int) -> Optional[str]:
        return self._get(f"api/applications/{protocol_id}/protocol")

    def get_status(self, protocol_id: int) -> Optional[str]:
        return self._get(f"api/applications/{protocol_id}/status")

    def get_verification(self, verification_id: str) -> Optional[str]:
        try:
            response = self.session.get(
                f"{self.BASE_URL}iaux/vri/{verification_id}",
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            return None

    def process_verification(self, verification_id: Optional[str]) -> Optional[VerificationRecord]:
        if not verification_id:
            return None

        response_text = self.get_verification(verification_id)
        if not response_text:
            return None

        try:
            payload = json.loads(response_text)["result"]
            verification_info = payload["vriInfo"]
            mi_info = payload["miInfo"]["singleMI"]
            cancelled = bool(
                re.search(
                    r"аннулирован",
                    payload.get("publication", {}).get("status", ""),
                    re.IGNORECASE,
                )
            )
            return VerificationRecord(
                number_verification=str(verification_id),
                date_verification=parse_date(verification_info.get("vrfDate")) or "",
                date_end_verification=parse_date(verification_info.get("validDate")),
                type_measuring_instrument=str(mi_info.get("mitypeType", "")),
                result_verification=(
                    CONCLUSION_VALID
                    if "applicable" in verification_info
                    else CONCLUSION_INVALID
                ),
                cancelled=cancelled,
            )
        except Exception:
            return None

    def get_report_data(self, protocol_id: int, num_threads: int = 1) -> Optional[ReportData]:
        report = self.get_report(protocol_id)
        if not report:
            return None

        try:
            xml_protocol = ET.fromstring(report)
        except ET.ParseError:
            return None

        records = xml_protocol.findall(".//appProcessed/record")
        verification_ids = []
        skipped_records = 0

        for record in records:
            global_id = record.findtext(".//success/globalID")
            if global_id:
                verification_ids.append(global_id)
            else:
                skipped_records += 1

        if len(verification_ids) > 10 and num_threads > 1:
            with futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
                responses = list(executor.map(self.process_verification, verification_ids))
        else:
            responses = [self.process_verification(item_id) for item_id in verification_ids]

        valid_records = []
        failed_requests = 0
        cancelled_records = 0

        for record in responses:
            if record is None:
                failed_requests += 1
            elif record.cancelled:
                cancelled_records += 1
            else:
                valid_records.append(record)

        return ReportData(
            records=valid_records,
            total_records=len(records),
            skipped_records=skipped_records,
            cancelled_records=cancelled_records,
            failed_requests=failed_requests,
        )


class XMLWriter:
    def __init__(self, max_records_in_file: int = MAX_RECORDS_IN_XML):
        self.max_records_in_file = max_records_in_file

    def write(
        self,
        folder: str,
        protocol_id: int,
        metrologist: Metrologist,
        records: list[VerificationRecord],
        save_method: int,
    ) -> list[str]:
        if not records:
            return []

        paths = []
        multipart = len(records) > self.max_records_in_file

        for index, start in enumerate(range(0, len(records), self.max_records_in_file), start=1):
            chunk = records[start:start + self.max_records_in_file]
            root = ET.Element("Message")
            data = ET.SubElement(root, "VerificationMeasuringInstrumentData")

            for record in chunk:
                item = ET.SubElement(data, "VerificationMeasuringInstrument")
                ET.SubElement(item, "NumberVerification").text = record.number_verification
                ET.SubElement(item, "DateVerification").text = record.date_verification
                if record.date_end_verification:
                    ET.SubElement(item, "DateEndVerification").text = record.date_end_verification
                ET.SubElement(item, "TypeMeasuringInstrument").text = record.type_measuring_instrument

                employee = ET.SubElement(item, "ApprovedEmployees")
                name = ET.SubElement(employee, "Name")
                ET.SubElement(name, "Last").text = metrologist.last_name
                ET.SubElement(name, "First").text = metrologist.first_name
                ET.SubElement(employee, "SNILS").text = metrologist.snils
                ET.SubElement(item, "ResultVerification").text = str(record.result_verification)

            ET.SubElement(root, "SaveMethod").text = str(save_method)

            filename = f"{protocol_id}_part{index}.xml" if multipart else f"{protocol_id}.xml"
            path = os.path.join(folder, filename)
            try:
                with open(path, "w", encoding="utf-8") as file:
                    file.write(ET.tostring(root, encoding="unicode"))
            except OSError as exc:
                raise IOError(f"Ошибка сохранения XML файла {path}: {exc}") from exc
            paths.append(path)

        return paths


class MetrologyForm:
    def __init__(self, master: tk.Tk):
        self.master = master
        self.master.withdraw()

        try:
            token = load_token()
            self.metrologists = load_metrologists()
        except ValueError as exc:
            messagebox.showerror("Ошибка", str(exc))
            os._exit(1)

        self.api = RestAPI(token)
        self.writer = XMLWriter()
        self.worker_thread: Optional[threading.Thread] = None

        self.metrologist_names = [m.full_name for m in self.metrologists]
        self._build_ui()
        self._center_window()
        self.master.deiconify()

    def _build_ui(self):
        self.master.title(f"Костыль 3.0 {VERSION}")
        self.master.resizable(False, False)

        tk.Label(self.master, text="Введите номер протокола АРШИН:").grid(
            row=0, column=0, padx=5, pady=5, sticky="w"
        )

        validate_cmd = self.master.register(lambda ch: ch.isdigit())
        self.number_entry = tk.Entry(
            self.master,
            validate="key",
            validatecommand=(validate_cmd, "%S"),
        )
        self.number_entry.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")

        tk.Label(self.master, text="Выберите метролога:").grid(
            row=1, column=0, padx=5, pady=5, sticky="w"
        )
        self.metrologist_var = tk.StringVar(value=self.metrologist_names[0])
        tk.OptionMenu(self.master, self.metrologist_var, *self.metrologist_names).grid(
            row=1, column=1, padx=5, pady=5, sticky="nsew"
        )

        tk.Label(self.master, text="Кол-во потоков:").grid(
            row=2, column=0, padx=5, pady=5, sticky="w"
        )
        self.threads_var = tk.StringVar(value="2")
        tk.OptionMenu(self.master, self.threads_var, "1", "2", "3", "4", "5").grid(
            row=2, column=1, padx=5, pady=5, sticky="nsew"
        )

        self.publish_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            self.master,
            text="Сохранять как черновики",
            variable=self.publish_var,
        ).grid(row=3, column=0, padx=5, pady=5, sticky="w")

        self.submit_button = tk.Button(
            self.master,
            text="Сформировать XML",
            command=self.submit_form,
            width=20,
        )
        self.submit_button.grid(row=4, column=0, columnspan=2, pady=10)

        self.overlay = tk.Canvas(self.master)
        self.overlay.grid(row=0, column=0, rowspan=5, columnspan=2, sticky="nsew")
        self.spinner = ttk.Progressbar(self.overlay, mode="indeterminate")
        self.spinner.pack(expand=True, fill="both")
        self.overlay.grid_remove()

    def _center_window(self):
        self.master.update_idletasks()
        w, h = self.master.winfo_width(), self.master.winfo_height()
        sw, sh = self.master.winfo_screenwidth(), self.master.winfo_screenheight()
        x, y = (sw - w) // 2, (sh - h) // 2
        self.master.geometry(f"{w}x{h}+{x}+{y}")

    def _toggle_spinner(self, show: bool):
        self.submit_button.configure(state=tk.DISABLED if show else tk.NORMAL)
        if show:
            self.overlay.grid()
            self.spinner.start(5)
        else:
            self.spinner.stop()
            self.overlay.grid_remove()

    def submit_form(self):
        protocol_id = safe_int(self.number_entry.get().strip())
        if protocol_id < MIN_PROTOCOL_ID:
            return

        metrologist = next(
            (m for m in self.metrologists if m.full_name == self.metrologist_var.get()),
            None,
        )
        if not metrologist:
            messagebox.showerror("Ошибка", "Не выбран метролог")
            return

        folder = filedialog.askdirectory()
        if not folder:
            return

        self._toggle_spinner(True)
        self.worker_thread = threading.Thread(
            target=self._process_create_xml,
            args=(
                folder,
                protocol_id,
                metrologist,
                2 - int(self.publish_var.get()),
                safe_int(self.threads_var.get(), 1),
            ),
            daemon=True,
        )
        self.worker_thread.start()

    def _process_create_xml(
        self,
        folder: str,
        protocol_id: int,
        metrologist: Metrologist,
        save_method: int,
        num_threads: int,
    ):
        start_time = time()
        try:
            report_data = self.api.get_report_data(protocol_id, num_threads)
            if not report_data:
                self.master.after(
                    0, lambda: messagebox.showerror("Ошибка", "Не удалось запросить протокол АРШИН")
                )
                return

            if report_data.failed_requests and not self._ask_continue(report_data.failed_requests):
                return

            files = self.writer.write(
                folder=folder,
                protocol_id=protocol_id,
                metrologist=metrologist,
                records=report_data.records,
                save_method=save_method,
            )
            if not files:
                self.master.after(
                    0, lambda: messagebox.showerror("Ошибка", "Ошибка сохранения XML файлов")
                )
                return

            elapsed = divmod(int(time() - start_time), 60)
            self.master.after(
                0,
                lambda: messagebox.showinfo(
                    "Успех",
                    self._build_success_message(report_data, len(files), elapsed),
                ),
            )
        except Exception as exc:
            self.master.after(0, lambda: messagebox.showerror("Ошибка", str(exc)))
        finally:
            self.master.after(0, lambda: self._toggle_spinner(False))

    def _ask_continue(self, failed_requests: int) -> bool:
        result = {"value": False}
        event = threading.Event()

        def ask():
            result["value"] = messagebox.askyesno(
                "Предупреждение",
                f"Сервер не отвечал и было пропущено {failed_requests} записей\n\n"
                f"Вы уверены, что хотите продолжить формирование XML?",
            )
            event.set()

        self.master.after(0, ask)
        event.wait()
        return result["value"]

    @staticmethod
    def _build_success_message(
        report_data: ReportData,
        total_files: int,
        elapsed: tuple[int, int],
    ) -> str:
        minutes, seconds = elapsed
        parts = [
            f"XML файлов сформировано {total_files}",
            f"Сохранено поверок: {len(report_data.records)} из {report_data.total_records}",
        ]
        if report_data.skipped_records:
            parts.append(f"Пропущено поверок из-за ошибки в протоколе: {report_data.skipped_records}")
        if report_data.failed_requests:
            parts.append(f"Пропущено поверок, т.к. сервер не отвечал: {report_data.failed_requests}")
        if report_data.cancelled_records:
            parts.append(f"Пропущено аннулированных: {report_data.cancelled_records}")
        parts.append(f"Затрачено времени: {minutes}:{seconds:02d}")
        return "\n\n".join(parts)


def main():
    root = tk.Tk()
    MetrologyForm(root)
    root.mainloop()


if __name__ == "__main__":
    main()
