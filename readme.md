# Костыль 3.0
Данный скрипт предназначен для автоматизации выгрузки данных о поверках из протоколов АРШИН в виде одного XML-пакета.

![](demo.gif)

## Классическая установка

1. [Установите Python версии 3](https://www.python.org/downloads/) (обязательно установить галочку Add Python to PATH).
2. Скачайте скрипт из репозитория.
3. Запустите bat-файл 'Установить зависимости.cmd' для установки python-пакетов.
4. В личном кабинете АРШИН создайте токен.
5. В конфигурационном файле 'token.txt' пропишите токен.
6. В файле 'metrologists.json' пропишите список поверителей и их СНИЛСы.

## Установка без Python

1. Скачайте в разделе релизов [версию упакованную в исполняемый EXE файл "EXE.version.zip"](https://github.com/Xekep/FSA-3.0/releases/latest).
2. В личном кабинете АРШИН создайте токен.
3. В конфигурационном файле 'token.txt' пропишите токен.
4. В файле 'metrologists.json' пропишите список поверителей и СНИЛСы.

## Использование
Запустите скрипт fsa. В окне введите номер протокола из АРШИН, выберите поверителя из выпадающего списка, укажите директорию сохранения XML-файлов. Если в протоколе больше 999 записей, то результат разбивается на несколько XML файлов.

## Лицензия
Данный скрипт распространяется под лицензией DWTFYWWI. Подробную информацию можно найти в файле LICENSE.
