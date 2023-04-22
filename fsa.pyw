import json, re, requests, os
import concurrent.futures, threading
from time import time
from typing import Optional, List
from datetime import datetime
from xml.etree import ElementTree
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from tkinter import filedialog
import xml.etree.ElementTree as ET

def get_metrologists_list() -> list:
    try:
        # Чтение файла с данными metrologists
        with open('metrologists.json', 'r', encoding='utf-8') as file:
            json_data = file.read()
        # Декодирование JSON-строки в список Python
        metrologists = json.loads(json_data)['metrologists']
        # Проверка соответствия структуре
        if isinstance(metrologists, list):
            for element in metrologists:
                if isinstance(element, dict):
                    if "LastName" in element and "FirstName" in element and "SNILS" in element:
                        if not all(isinstance(element[field], str) for field in ["LastName", "FirstName", "SNILS"]):
                            raise ValueError("Элемент содержит некорректные данные")
                    else:
                        raise ValueError("Элемент не содержит всех необходимых полей")
                else:
                    raise ValueError("Элемент не является объектом")
        else:
            raise ValueError("Данные не содержат массива")
        return metrologists
    except:
        return None

def get_token() -> str:
    try:
        with open('token.txt', 'r') as f:
            token = f.read().strip()
            pattern = r'^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$'
            if not re.match(pattern, token, re.IGNORECASE):
                return None
            return token
    except:
        return None

def createXML(folder, protocol_id, metrologist, records, save_method):
    if not records:
        return []

    file_counter = 0
    xml_array = []
    xml = ET.Element('Message')
    multipart = True if len(records) > 999 else False

    # Создание элемента VerificationMeasuringInstrumentData
    verification_measuring_instrument_data = ET.SubElement(xml, 'VerificationMeasuringInstrumentData')

    for index, record in enumerate(records):
        verification_measuring_instrument = ET.SubElement(verification_measuring_instrument_data, 'VerificationMeasuringInstrument')
        ET.SubElement(verification_measuring_instrument, 'NumberVerification').text = str(record['NumberVerification'])
        ET.SubElement(verification_measuring_instrument, 'DateVerification').text = str(record['DateVerification'])
        if record['DateEndVerification'] is not None:
            ET.SubElement(verification_measuring_instrument, 'DateEndVerification').text = str(record['DateEndVerification'])
        ET.SubElement(verification_measuring_instrument, 'TypeMeasuringInstrument').text = str(record['TypeMeasuringInstrument'])
        approved_employee = ET.SubElement(verification_measuring_instrument, 'ApprovedEmployee')
        name = ET.SubElement(approved_employee, 'Name')
        ET.SubElement(name, 'Last').text = metrologist['LastName']
        ET.SubElement(name, 'First').text = metrologist['FirstName']
        ET.SubElement(approved_employee, 'SNILS').text = metrologist['SNILS']
        ET.SubElement(verification_measuring_instrument, 'ResultVerification').text = str(record['ResultVerification'])

        # Создание нового файла XML при достижении максимального количества записей
        if (index + 1) % 999 == 0:
            file_counter += 1
            file_name = os.path.join(folder, str(protocol_id)) + (f'_part{file_counter}' if multipart else '') + '.xml'
            ET.SubElement(xml, 'SaveMethod').text = str(save_method)
            xml_string = ET.tostring(xml, encoding='unicode')
            try:
                with open(file_name, 'w', encoding='utf-8') as f:
                    f.write(xml_string)
            except IOError:
                return None
            xml_array.append(file_name)
            xml = ET.Element('Message')
            verification_measuring_instrument_data = ET.SubElement(xml, 'VerificationMeasuringInstrumentData')

    # Добавление оставшихся записей в последний файл
    if len(verification_measuring_instrument_data) > 0:
        file_counter += 1
        file_name = os.path.join(folder, str(protocol_id)) + (f'_part{file_counter}' if multipart else '') + '.xml'
        ET.SubElement(xml, 'SaveMethod').text = str(save_method)
        xml_string = ET.tostring(xml, encoding='unicode')
        try:
            with open(file_name, 'w', encoding='utf-8') as f:
                f.write(xml_string)
        except IOError:
            return None
        xml_array.append(file_name)

    return xml_array

class RestAPI:
    ARSHIN_BASE_URL = 'https://fgis.gost.ru/fundmetrology/cm/'

    def __init__(self, token: str) -> None:
        self.token = token

    def get_report(self, id: int) -> Optional[str]:
        url = f'{self.ARSHIN_BASE_URL}api/applications/{id}/protocol'
        headers = {'Authorization': f'Bearer {self.token}'}
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.text.replace('gost:', '')
        except requests.exceptions.RequestException:
            return None

    def process_verification(self, id: int):
        response = self.verification(id)
        if not response:
            return None
        verification = json.loads(response)['result']
        mitype = verification['miInfo']['singleMI']['mitypeType']
        vrf_date = datetime.strptime(verification['vriInfo']['vrfDate'], '%d.%m.%Y').strftime('%Y-%m-%d')
        valid_date = verification['vriInfo'].get('validDate', None)
        if valid_date:
            valid_date = datetime.strptime(valid_date, '%d.%m.%Y').strftime('%Y-%m-%d')
        applicable = verification['vriInfo'].get('applicable', None)
        conclusion = 1 if applicable else 2  # 1 - пригоден, 2 - непригоден
        return {
            'TypeMeasuringInstrument': mitype,
            'DateVerification': vrf_date,
            'DateEndVerification': valid_date,
            'ResultVerification': conclusion,
            'NumberVerification': id,
        }

    def get_report_data(self, id: int) -> Optional[List[dict]]:
        responses_data = []

        # Получение данных для формирования XML
        report = self.get_report(id)
        if report is None:
            return None
        
        xml_protocol = ElementTree.fromstring(report)
        records = xml_protocol.find('.//appProcessed').findall('record')
        records = [record for record in xml_protocol.findall('.//appProcessed/record')]
        verifications = []
        missing_counter = 0

        for record in records:
            global_id = record.findtext('.//success/globalID', default=None)
            if global_id:
                verifications.append(global_id)
            else:
                missing_counter += 1
        
        if len(verifications) > 10:
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                results = executor.map(self.process_verification, verifications)
                responses_data.extend(list(results))
        else:
            responses_data = [self.process_verification(id) for id in verifications]

        failed_requests = 0
        verification_data = []
        for response in responses_data:
            if not response:
                failed_requests += 1
            else:
                verification_data.append(response)

        return {
            'records': verification_data,
            'total_records': len(records),
            'saved_records': len(verification_data),
            'skipped_records': missing_counter,
            'failed_requests': failed_requests
        }

    def status(self, id: int) -> Optional[str]:
        url = f'{self.ARSHIN_BASE_URL}api/applications/{id}/status'
        headers = {'Authorization': f'Bearer {self.token}'}
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.text.replace('gost:', '')
        except requests.exceptions.RequestException:
            return None

    def verification(self, id: str) -> Optional[str]:
        url = f'{self.ARSHIN_BASE_URL}iaux/vri/{id}'
        try:
            response = requests.get(url)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException:
            return None

class MetrologyForm:           
    def __init__(self, master):
        self.master = master
        token = get_token()
        if token == None or len(token) == 0:
            messagebox.showerror('Ошибка', 'Токен не найден')
            os._exit(1)
        self.metrologists_list = get_metrologists_list()
        if self.metrologists_list == None or len(self.metrologists_list) == 0:
            messagebox.showerror('Ошибка', 'Не удалось считать metrologists.json')
            os._exit(1)
        self.metrologists = [f"{d['LastName']} {d['FirstName']}" for d in self.metrologists_list]             
        self.restapi = RestAPI(token)
        self.master.title('Костыль 3.0 v1.4')
        self.master.resizable(False, False)
        self.master.bind("<Control-KeyPress>", self.keypress)
        
        # Создаем метку и поле ввода для чисел
        self.number_label = tk.Label(self.master, text='Введите номер протокола АРШИН:')
        self.number_label.grid(row=0, column=0)
        self.validate_cmd = self.master.register(self._validate_input)
        self.number_entry = tk.Entry(self.master, validate='key', validatecommand=(self.validate_cmd, '%S'))
        self.number_entry.grid(row=0, column=1, sticky='NSEW')

        # Добавляем контекстное меню
        self.menu = tk.Menu(tearoff=0)
        #self.menu.add_command(label='Копировать', accelerator='Ctrl+С', command=lambda: self.w.focus_force() or self.w.event_generate('<<Copy>>'))
        self.menu.add_command(label='Вставить', accelerator='Ctrl+V', command=lambda: self.w.focus_force() or self.w.event_generate('<<Paste>>'))
        self.number_entry.bind('<Button-3>', self._show_menu)
        
        # Создаем выпадающий список на основе данных из файла
        self.metrologist_label = tk.Label(self.master, text='Выберите метролога:')
        self.metrologist_label.grid(row=1, column=0, sticky='W')
        self.metrologist_var = tk.StringVar(self.master)
        self.metrologist_var.set(self.metrologists[0])
        self.metrologist_optionmenu = tk.OptionMenu(self.master, self.metrologist_var, *self.metrologists)
        self.metrologist_optionmenu.grid(row=1, column=1, sticky='NSEW')
        
        # Создаем чекбокс для опубликования результата
        self.publish_var = tk.BooleanVar(self.master)
        self.publish_checkbutton = tk.Checkbutton(self.master, text='Сохранять как черновики', variable=self.publish_var)
        self.publish_checkbutton.grid(row=2, column=0, sticky='W')
        
        # Создаем кнопку для отправки данных
        self.submit_button = tk.Button(self.master, text='Сформировать XML', command=self.submit_form, width=20)
        self.submit_button.grid(row=3, column=0, columnspan=2, pady=10)
        
        # создаем холст в центре формы
        self.canvas = tk.Canvas(self.master)
        self.canvas.grid(row=0, column=0, rowspan=4, columnspan=2, sticky='NSEW')
        
        # Создаем спиннер
        self.spinner = ttk.Progressbar(self.canvas, mode='indeterminate')
        self.spinner.pack(expand=True, fill='both')
        self.spinner.start(5)
        self.canvas.grid_remove()        
        
        # Установить окно по центру главного экрана
        self._set_window_center()
        
        # Показать окно
        root.deiconify()

    def keypress(self, e):
        if e.keycode == 86 and e.keysym != 'v':
            try:
                text = self.master.clipboard_get()
                if text:
                    focused_widget = self.master.focus_get()
                    focused_widget.event_generate("<<Paste>>")
            except:
                pass
        elif e.keycode == 67 and e.keysym != 'c':
            try:
                text = self.master.selection_get()
                if text:
                    self.master.clipboard_clear()
                    self.master.clipboard_append(text)
            except:
                pass
        elif e.keycode == 88 and e.keysym != 'x':
            try:
                text = self.master.selection_get()
                if text:
                    self.master.clipboard_clear()
                    self.master.clipboard_append(text)
                    focused_widget = self.master.focus_get()
                    focused_widget.event_generate("<<Cut>>")
            except:
                pass
        elif e.keycode == 65 and e.keysym != 'x':
                focused_widget = self.master.focus_get()
                if isinstance(focused_widget, tk.Entry):
                   focused_widget.select_range(0, tk.END)

    def _show_menu(self, event):
        self.menu.post(event.x_root, event.y_root)
        self.w = event.widget

    def _set_window_center(self):
        self.master.update_idletasks()
        screen_width = self.master.winfo_screenwidth()
        screen_height = self.master.winfo_screenheight()
        width = self.master.winfo_width()
        height = self.master.winfo_height()
        x = int((screen_width / 2) - (width / 2))
        y = int((screen_height / 2) - (height / 2))
        self.master.geometry(f'{width}x{height}+{x}+{y}')
        
    def _validate_input(self, input_char):
        if not input_char.isdigit():
            return False
        return True

    def process_create_xml(self, folder_selected, protocol_id, metrologists_i, save_method):
        start_time  = time()
        report_data = self.restapi.get_report_data(protocol_id);
        if report_data:
                failed_requests = report_data['failed_requests']
                if failed_requests:
                    result = messagebox.askyesno('Предупреждение', f'Сервер не отвечал и было пропущено {failed_requests} записей\n\nВы уверены, что хотите продолжить формирование XML?')
                    if not result:
                        self._hide_spinner()
                        return
                metrologist = self.metrologists_list[metrologists_i]
                files = createXML(folder_selected, protocol_id, metrologist, report_data['records'], save_method)
                if files:
                    total_files = len(files)
                    total_records = report_data['total_records']
                    saved_records = report_data['saved_records']
                    skipped_records = report_data['skipped_records']
                    message = f'XML файлов сформировано {total_files}\n\nСохранено поверок {saved_records} из {total_records}'
                    if skipped_records > 0:
                        message += f'\n\nПропущено поверок с ошибками {skipped_records}'
                    message += '\n\nзатрачено времени %d:%02d\n\n' % divmod(time() - start_time, 60)
                    messagebox.showinfo('Успех', message)
                else:
                    messagebox.showerror('Ошибка', 'Ошибка сохранения XML файлов') 
        else:
                messagebox.showerror('Ошибка', 'Не удалось запросить протокол АРШИН')
        self._hide_spinner()
    
    def submit_form(self):
        # Считываем введенные данные
        protocol_id = self.number_entry.get()
        protocol_id = 0 if not protocol_id else int(protocol_id)
        if protocol_id < 100000:
            return
        metrologist = self.metrologist_var.get()
        metrologists_i = self.metrologists.index(metrologist)
        save_method = 2 - self.publish_var.get() # 1 - черновик, 2 - отправлено
        self._show_spinner()
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            t = threading.Thread(target=self.process_create_xml, args=(folder_selected, protocol_id, metrologists_i, save_method))
            t.start()
        else:
            self._hide_spinner()
        
    def _show_spinner(self):
        self.canvas.grid()
                
    def _hide_spinner(self):
        self.canvas.grid_remove()

# Создаем окно приложения
root = tk.Tk()
# Скрыть окно
root.withdraw()
# Создаем экземпляр формы
form = MetrologyForm(root)

# Запускаем главный цикл обработки событий
root.mainloop()
