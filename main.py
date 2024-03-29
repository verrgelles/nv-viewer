import os
import random
import socket
import time

import matplotlib
import numpy as np
import pandas as pd
import serial.tools.list_ports
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QMainWindow, QLineEdit, QPushButton, QLabel, QFileDialog
from matplotlib.backends.backend_qt import NavigationToolbar2QT
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.backends.backend_template import FigureCanvas
from matplotlib.figure import Figure
from scipy.interpolate import interp1d

import odmrd_pb2


def find_com_port() -> str:
    """
    Returns:
        str: ком-порт платы в формате COMX
    """
    ports = [[port.manufacturer, port.device] for port in list(serial.tools.list_ports.comports())]
    for i in range(len(ports)):
        if 'FTDI' in ports[i][0]:
            return ports[i][1]


# Deprecated
def target_voltage(target_mech_angle: float, scaling_factor: float) -> float:
    """
    Args:
        target_mech_angle (float): механический угол, который хотим задать (может быть >(<) 0
        scaling_factor (float): scaling factor
    Returns:
         float: Возвращает значение напряжения в диапазоне [-target_mech_angle;target_mech_angle] * scaling_factor Вольт
    """
    return target_mech_angle * scaling_factor


def voltage_centering(target_voltage: float) -> float:
    """
    Сдвигает значение 0-го напряжения в точку 10 Вольт
    Args:
        target_voltage (float): рассчитанное значение напряжения
    """
    return target_voltage + 10


def voltage_to_duty_cycle(target_voltage: float) -> str:
    """
        Args:
            target_voltage (float): целевое значение напряжения

        Returns:
            float: коэффициент заполнения ШИМ с коррекцией
        """
    d = pd.read_csv('pwm_correction.csv')
    correction = interp1d(d['Реальное напряжение'], d['Коэффициент заполнения ШИМ'])
    return format(float(correction(target_voltage)), '.3f')


def send_command(serial: serial.Serial, x_voltage: float, y_voltage: float):
    """
    Отправляет команду изменения положения зеркал на плату

    Args:
        serial: экземпляр класса Serial, предварительно сконфигурированный
        x_voltage (float): значение напряжения для зеркала X
        y_voltage (float): значение напряжения для зеркала Y
    """
    serial.write(
        f"{voltage_to_duty_cycle(x_voltage)}|{voltage_to_duty_cycle(y_voltage)}F".encode()
    )


def read_callback(serial: serial.Serial) -> list:
    x = serial.read(6)
    y = serial.read(6)
    return [x, y]


def quantum_level(value: str) -> int:
    """
    Преобразовывает сырой callback уровня квантования в число
    """
    t = ''
    for s in value:
        try:
            t += str(int(s))
        except ValueError:
            pass
    return int(t)


def callback_to_voltage(value: str) -> float:
    """
    Преобразует полученный callback в напряжение (для коррекции моторов)
    """
    q_level = quantum_level(value)
    return float(3.3 / 4096 * q_level * 11.48)


def normalize_callback(serial: serial.Serial) -> list[float]:
    t = read_callback(serial)
    x, y = t[0], t[1]
    x = callback_to_voltage(x)
    y = callback_to_voltage(y)
    return [x, y]


def get_number_of_photons(time_to_collect: float, frequency=2500000000, gain=0.0) -> float:
    """
    Функция для подсчёта количества фотонов
    Args:
        time_to_collect (float): время накопления количества фотонов (в секундах)
        frequency (int): частота
        gain: усиление?

    Returns:
        Возвращает количество накопленных фотонов
    """

    odmr_board_ip = '192.168.0.2'  # The server's hostname or IP address board: 192.168.1.64 192.168.0.2
    odmr_board_port = 9100  # The port used by the server

    width = time_to_collect * 1000000

    # формирование сообщения о начале сканирования
    txmsg = odmrd_pb2.Msg()
    txmsg.rw = True
    txmsg.txCh.mode = odmrd_pb2.SINGLE  # odmrd_pb2.SCAN
    txmsg.txCh.curr_hz = 0
    txmsg.txCh.start_hz = int(frequency)
    txmsg.txCh.stop_hz = txmsg.txCh.start_hz + 1000  # 2500000099
    txmsg.txCh.step_hz = 100
    txmsg.txCh.gain_dbm = gain
    txmsg.txCh.pulse_width_us = int(width)
    txmsg.txCh.photon_cnt_enable = True

    txmsg.txCh.min_hz = 0
    txmsg.txCh.max_hz = 0
    txmsg.txCh.min_step_hz = 0
    txmsg.txCh.max_step_hz = 0
    txmsg.txCh.min_gain_dbm = 0
    txmsg.txCh.max_gain_dbm = 0
    txmsg.txCh.min_pulse_width_us = 0
    txmsg.txCh.max_pulse_width_us = 0

    # отправка сообщения о начале сканирования
    try:
        sockfd = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sockfd.settimeout(4)
        sockfd.connect((odmr_board_ip, odmr_board_port))
        sockfd.sendall(txmsg.SerializeToString())
        rxBuf = sockfd.recv(1024)

        r_msg = odmrd_pb2.Msg()
        r_msg.ParseFromString(rxBuf)
    except Exception as e:
        print("Sending start message failed with ", e)
        return

    time.sleep(1.5 * time_to_collect)
    # формирование сообщения для приема данных
    msg = odmrd_pb2.Msg()
    msg.rw = False
    msg.txCh.curr_hz = 0
    msg.txCh.photon_cnt_val.extend([0])
    msg.txCh.photon_cnt_len = 0
    txmsg.txCh.gain_dbm = gain
    msg_serialized = msg.SerializeToString()

    try:
        sockfd.sendall(msg_serialized)
        time.sleep(0.1)
        # прием данных
        rxBuf = sockfd.recv(8192)
    except Exception:
        pass

    # десериализация сообщения с полученными данными
    r_msg.Clear()
    r_msg.ParseFromString(rxBuf)

    if len(r_msg.txCh.photon_cnt_val) >= 1:
        # вернуть измеренное количество фотонов в заданной точке
        return r_msg.txCh.photon_cnt_val[0]
    else:
        return 0


def coordinate_to_real_voltage(coordinate: float, k: float):
    """
    Переводит координату в напряжение в диапазоне [-1.2, 1.2]В
    Args:
        coordinate (float): координата в микронах
        k (float): Вольт/Микрон

    Returns:
        Напряжение в диапазоне [-1.2, 1.2]В
    """
    return coordinate * k


def mapping(serial: serial.Serial, time_to_collect: float, x_start: float, x_stop: float, x_step: float, y_start: float,
            y_stop: float, y_step: float, k: float) -> \
        list[list[float]]:
    """
    Args:
        serial: экземпляр класса Serial
        time_to_collect (float): время накопления фотонов (в секундах)
        x_start (float): начальное положение по оси x (в микронах)
        x_stop (float): конечное положение по оси x (в микронах)
        x_step (float): шаг по оси x (в микронах)
        y_start (float): начальное положение по оси y (в микронах)
        y_stop (float): конечное положение по оси y (в микронах)
        y_step (float): шаг по оси y (в микронах)
        k(float): Вольт/Микрон

    Returns:
        Возвращает матрицу с значениями числа фотонов
    """
    x = np.arange(x_start, x_stop, x_step) * k
    y = np.arange(y_start, y_stop, y_step) * k

    time = len(x) * len(y) * time_to_collect
    print(time)

    result = []
    for i in x:
        string = []
        for j in y:
            send_command(serial, i, j)
            string.append(get_number_of_photons(time_to_collect))
        result.append(string)

    return result


def hex_to_RGB(hex_str):
    return [int(hex_str[i:i + 2], 16) for i in range(1, 6, 2)]


def get_color_gradient(c1, c2, n):
    assert n > 1
    c1_rgb = np.array(hex_to_RGB(c1)) / 255
    c2_rgb = np.array(hex_to_RGB(c2)) / 255
    mix_pcts = [x / (n - 1) for x in range(n)]
    rgb_colors = [((1 - mix) * c1_rgb + (mix * c2_rgb)) for mix in mix_pcts]
    return ["#" + "".join([format(int(round(val * 255)), "02x") for val in item]) for item in rgb_colors]

class MplCanvas(FigureCanvasQTAgg):
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = fig.add_subplot(111)
        super(MplCanvas, self).__init__(fig)


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()

        self.com_port = find_com_port()
        self.map_path = None
        self.scale_factor = 0.8
        self.canvas = MplCanvas(self, width=5, height=5, dpi=100)
        self.x_angle = None
        self.y_angle = None

        self.setWindowTitle("\n")

        self.input_x_angle = QLineEdit()
        self.input_x_angle.setPlaceholderText("∠x")
        self.input_x_angle.textChanged.connect(self.x_angle_chosen)

        self.input_y_angle = QLineEdit()
        self.input_y_angle.setPlaceholderText("∠y")
        self.input_y_angle.textChanged.connect(self.y_angle_chosen)

        self.open_map_button = QPushButton("Открыть карту")
        self.open_map_button.clicked.connect(self.open_map_button_clicked)

        self.start_button = QPushButton("Начать картирование")
        self.start_button.clicked.connect(self.start_button_clicked)

        def convert_csv_to_mpl(df: pd.DataFrame):
            from math import isnan
            t = []
            for y in sorted(set(df['y']), reverse=True):
                x_values = []
                for x in (df.where(df['y'] == y))['v']:
                    if not isnan(x):
                        x_values.append(x)
                t.append(x_values)
            return sorted(set(df['x'])), sorted(set(df['y']), reverse=True), t

        data = convert_csv_to_mpl(pd.read_csv('test_1.csv'))
        cmap = matplotlib.colors.ListedColormap(get_color_gradient("#000000", "#ff0000", 2000))
        xlabs = data[0]
        ylabs = data[1]

        self.canvas.axes.imshow(cmap=cmap, X=data[2])
        self.canvas.axes.set_xticks(np.arange(len(xlabs)), labels = xlabs)
        self.canvas.axes.set_yticks(np.arange(len(ylabs)), labels = ylabs)

        toolbar = NavigationToolbar2QT(self.canvas, self)

        layout = QVBoxLayout()
        widgets = [
            toolbar,
            self.canvas,
            self.input_x_angle,
            self.input_y_angle,
            self.open_map_button,
            self.start_button
        ]

        for widget in widgets:
            layout.addWidget(widget)

        widget = QWidget()
        widget.setLayout(layout)

        self.setCentralWidget(widget)

    def x_angle_chosen(self, i):
        self.x_angle = i

    def y_angle_chosen(self, i):
        self.y_angle = i


    def open_map_button_clicked(self):
        response = QFileDialog.getOpenFileNames(
            parent=self,
            caption='Выберите файл карты',
            directory=os.getcwd(),
            filter='CSV File (*.csv)'
        )
        self.map_path = response[0]
        self.canvas.axes.cla()
        self.canvas.axes.imshow(X=[[0,1,2,3], [4,5,6,7]])

    def start_button_clicked(self):
        scale_factor = float(self.scale_factor)
        t_x_angle = float(self.x_angle)
        t_y_angle = float(self.y_angle)

        x_target_voltage = target_voltage(t_x_angle, scale_factor)
        x_target_voltage_centered = voltage_centering(x_target_voltage)

        y_target_voltage = target_voltage(t_y_angle, scale_factor)
        y_target_voltage_centered = voltage_centering(y_target_voltage)

        ser = serial.Serial(self.com_port, 115200)
        send_command(ser, x_target_voltage_centered, y_target_voltage_centered)
        ser.close()


def main():
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


def test_walk():
    ser = serial.Serial('COM5', 115200)
    ser.write(f"0.172|0.172F".encode())
    f = open('test_1.csv', 'w')
    for x in (np.arange(0.116, 0.134, 0.001)):
        x = str(x)[:5]
        if len(x) == 4:
            x = f'{x}0'
        for y in (np.arange(0.115, 0.149, 0.001)):
            y = str(y)[:5]
            if len(y) == 4:
                y = f'{y}0'
            ser.write(f"{x}|{y}F".encode())
            time.sleep(1.0)
            # f.write(f'"({x}, {y})",{get_number_of_photons(1.0)}\n')
    f.close()


# По (116,115) правый верхний
# По (134,149) левый нижний

# центр 0.123, 0.130

# x 0.120-0.126
# y 0.126-0.134

# 0.128, 0.126
# x 0.125-0.131
# y 0.122-0.130
if __name__ == '__main__':
    ser = serial.Serial('COM3', 115200)
    #f = open('test.csv', 'w')
    ser.write(f"0.000|0.100F".encode())
    k = 0
    for x in (np.arange(0.000, 3.300, 0.001)):
        x = format(float(x), '.3f')
        for y in (np.arange(0.100, 3.300, 0.001)):
            k+=1
            y = format(float(y), '.3f')
            ser.write(f"{x}|{y}F".encode())
            print(f"{x}|{y}F", k)
            time.sleep(1)