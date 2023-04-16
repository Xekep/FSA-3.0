import json, re, requests, os
from typing import Optional, List
from datetime import datetime
from xml.etree import ElementTree
import tkinter as tk
from tkinter import messagebox
from tkinter import filedialog
import xml.etree.ElementTree as ET
from dateutil.parser import parse

def get_metrologists_list() -> list:
    #try:
        # Чтение файла с данными metrologists
        with open('metrologists.json', 'r', encoding='utf-8') as file:
            json_data = file.read()
        # Декодирование JSON-строки в список Python
        metrologists = json.loads(json_data)['metrologists']
        return metrologists
    #except:
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

def createXML(folder, protocol_id, first_name, last_name, snils, records, save_method):
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
        ET.SubElement(name, 'Last').text = last_name
        ET.SubElement(name, 'First').text = first_name
        ET.SubElement(approved_employee, 'SNILS').text = str(snils)
        ET.SubElement(verification_measuring_instrument, 'ResultVerification').text = str(record['ResultVerification'])

        # Создание нового файла XML при достижении максимального количества записей
        if (index + 1) % 999 == 0:
            file_counter += 1
            file_name = os.path.join(folder, protocol_id) + ('_part{file_counter}' if multipart else '') + '.xml'
            ET.SubElement(xml, 'SaveMethod').text = str(save_method)
            xml_string = ET.tostring(xml, encoding='unicode')
            with open(file_name, 'w', encoding='utf-8') as f:
                f.write(xml_string)
            xml_array.append(file_name)
            xml = ET.Element('Message')
            verification_measuring_instrument_data = ET.SubElement(xml, 'VerificationMeasuringInstrumentData')

    # Добавление оставшихся записей в последний файл
    if len(verification_measuring_instrument_data) > 0: # 9127046
        file_counter += 1
        file_name = os.path.join(folder, protocol_id) + ('_part{file_counter}' if multipart else '') + '.xml'
        ET.SubElement(xml, 'SaveMethod').text = str(save_method)
        xml_string = ET.tostring(xml, encoding='unicode')
        with open(file_name, 'w', encoding='utf-8') as f:
            f.write(xml_string)
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

    def get_report_data(self, id: int) -> Optional[List[dict]]:
        verification_data = []

        # Получение данных для формирования XML
        report = self.get_report(id)
        if report is None:
            return None

        xml_protocol = ElementTree.fromstring(report)
        records = xml_protocol.find('.//appProcessed').findall('record')

        for record in records:
            verification_id = record.find('.//success/globalID').text
            verification = json.loads(self.verification(verification_id))['result']
            modification = verification['miInfo']['singleMI']['modification']
            vrf_date = parse(verification['vriInfo']['vrfDate']).strftime('%Y-%m-%d')
            valid_date = verification['vriInfo'].get('validDate', None)
            if valid_date:
                vrf_date = parse(valid_date).strftime('%Y-%m-%d')
            applicable = verification['vriInfo'].get('applicable', None)
            conclusion = 1 if applicable else 2  # 1 - пригоден, 2 - непригоден
            verification_data.append({
                'TypeMeasuringInstrument': modification,
                'DateVerification': vrf_date,
                'DateEndVerification': valid_date,
                'ResultVerification': conclusion,
                'NumberVerification': verification_id,
            })
        return verification_data

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

        token = get_token()
        if token == None or len(token) == 0:
            messagebox.showerror('Ошибка', 'Токен не найден')
            exit()
        self.metrologists_list = get_metrologists_list()
        if self.metrologists_list == None or len(self.metrologists_list) == 0:
            messagebox.showerror('Ошибка', 'Не удалось считать metrologists.json')
            exit()
        self.metrologists = [f"{d['LastName']} {d['FirstName']}" for d in self.metrologists_list]             
        self.restapi = RestAPI(token)
        self.master = master
        self.master.title('Костыль 3.0')
        self.master.resizable(False, False)
        
        # Создаем метку и поле ввода для чисел
        self.number_label = tk.Label(self.master, text='Введите номер протокола АРШИН:')
        self.number_label.grid(row=0, column=0, sticky='W')
        self.validate_cmd = self.master.register(self._validate_input)
        self.number_entry = tk.Entry(self.master, validate='key', validatecommand=(self.validate_cmd, '%S'))
        self.number_entry.grid(row=0, column=1)
        
        # Создаем выпадающий список на основе данных из файла
        self.metrologist_label = tk.Label(self.master, text='Выберите метролога:')
        self.metrologist_label.grid(row=1, column=0, sticky='W')
        self.metrologist_var = tk.StringVar(self.master)
        self.metrologist_var.set(self.metrologists[0])
        self.metrologist_optionmenu = tk.OptionMenu(self.master, self.metrologist_var, *self.metrologists)
        self.metrologist_optionmenu.grid(row=1, column=1, sticky='NSEW')
        
        # Создаем чекбокс для опубликования результата
        self.publish_var = tk.BooleanVar(self.master)
        self.publish_checkbutton = tk.Checkbutton(self.master, text='Черновики', variable=self.publish_var)
        self.publish_checkbutton.grid(row=2, column=0, sticky='W')
        
        # Создаем кнопку для отправки данных
        self.submit_button = tk.Button(self.master, text='Сформировать XML', command=self.submit_form, width=20)
        self.submit_button.grid(row=3, column=0, columnspan=2, pady=10)
        
    def _validate_input(asd, typ):
        if not typ.isdigit():
            return False
        return True
    
    def submit_form(self):
        # Считываем введенные данные
        protocol_id = self.number_entry.get()
        metrologist = self.metrologist_var.get()
        metrologists_i = self.metrologists.index(metrologist)
        save_method = 2 - self.publish_var.get() # 1 - черновик, 2 - отправлено
        folder_selected = filedialog.askdirectory()
        records = self.restapi.get_report_data(protocol_id);
        if records == None:
            messagebox.showerror('Ошибка', 'Не удалось запросить протокол АРШИН')
            return
        first_name = self.metrologists_list[metrologists_i]['FirstName']
        last_name = self.metrologists_list[metrologists_i]['LastName']
        snils = self.metrologists_list[metrologists_i]['SNILS']
        if createXML(folder_selected, protocol_id, first_name, last_name, snils, records, save_method):
            messagebox.showinfo('Успех', 'XML файлы были сохранены')
        else:
            messagebox.showerror('Ошибка', 'Ошибка сохранения XML файлов')
        


# Создаем окно приложения
root = tk.Tk()

# Создаем экземпляр формы
form = MetrologyForm(root)

# Запускаем главный цикл обработки событий
root.mainloop()