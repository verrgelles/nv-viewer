import serial.tools.list_ports
import csv
from PyQt5.QtMultimedia import QCameraInfo, QCamera
from PyQt5.QtMultimediaWidgets import QCameraViewfinder
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QMainWindow, QLineEdit, QPushButton, QComboBox, QLabel, \
    QGridLayout
import pandas as pd
import numpy as np
from scipy import interpolate
from scipy.interpolate import interp1d


def find_com_port() -> str:
    """
    Returns:
        str: ком-порт платы в формате COMX
    """
    ports = [[port.manufacturer, port.device] for port in list(serial.tools.list_ports.comports())]
    for i in range(len(ports)):
        if 'FTDI' in ports[i][0]:
            return ports[i][1]


def target_voltage(target_mech_angle: float, scaling_factor: float) -> float:
    """
    Args:
        target_mech_angle (float): механический угол, который хотим задать (может быть >(<) 0
        max_mech_angle (float): максимальный механический угол (>0)
        scaling_factor (float): scaling factor
    Returns:
         float: Возвращает значение напряжения в диапазоне [0; (max_mech_angle + target_mech_angle) * scaling_factor] Вольт
    """

    return target_mech_angle * scaling_factor


def max_voltage(max_mech_angle: float, scaling_factor: float) -> float:
    """
    Args:
        max_mech_angle (float): максимальный механический угол (>0)
        scaling_factor (float): scaling factor
    Returns:
        float: Максимальное значение напряжения для данной конфигурации
    """
    return max_mech_angle * scaling_factor * 2


def voltage_centralization(target_voltage: float) -> float:
    return target_voltage + 10


def voltage_to_duty_cycle(target_voltage: float) -> str:
    d = pd.read_csv('data.csv')
    f = interp1d(d['Реальное напряжение'], d['Коэффициент заполнения ШИМ'])
    return format(float(f(target_voltage)), '.3f')


def send_command(serial: serial.Serial, x_voltage: float, y_voltage: float):
    """
    Отправляет команду изменения положения зеркал на плату

    Args:
        serial: экземпляр класса Serial, предварительно сконфигурированный
        x_voltage (float): значение напряжения для зеркала X
        y_voltage (float): значение напряжения для зеркала Y
        pwm_max_voltage (float): максимальное значения напряжения ШИМ
    """
    serial.write(
        f"{voltage_to_duty_cycle(x_voltage)}|{voltage_to_duty_cycle(y_voltage)}F".encode()
    )


class CameraWindow(QWidget):
    def __init__(self):
        super(CameraWindow, self).__init__()

        self.setWindowTitle("\n")

        self.camera = None

        layout = QVBoxLayout()

        cameras = QCameraInfo.availableCameras()

        for camera in cameras:
            self.camera = camera
            print(camera.description())

        self.camera_view_finder = QCameraViewfinder()
        layout.addWidget(self.camera_view_finder)
        self.setLayout(layout)
        self.get_camera()

    def get_camera(self):
        self.camera = QCamera(self.camera)
        self.camera.setViewfinder(self.camera_view_finder)
        self.camera.setCaptureMode(QCamera.CaptureStillImage)
        self.camera.start()


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()

        self.com_port = None
        self.camera_widget = None
        self.pwm_max_voltage = None
        self.scale_factor = None
        self.scale_factors = ["0.5", "0.8", "1"]
        self.x_angle = None
        self.y_angle = None

        self.setWindowTitle("\n")

        com_port_selector = QLabel()
        self.com_port = find_com_port()
        com_port_selector.setText(f"COM-порт: {self.com_port}")

        scale_factor_selector = QComboBox()
        scale_factor_selector.setPlaceholderText("Выберите scaling factor")
        scale_factor_selector.insertItems(0, self.scale_factors)
        scale_factor_selector.currentIndexChanged.connect(self.scale_factor_chosen)
        scale_factor_selector.setCurrentIndex(1)

        input_pwm_max_voltage = QLineEdit()
        input_pwm_max_voltage.setPlaceholderText("Введите max напряжение ШИМ")
        input_pwm_max_voltage.textChanged.connect(self.pwm_max_voltage_chosen)
        input_pwm_max_voltage.setText('20')

        self.input_x_angle = QLineEdit()
        self.input_x_angle.setPlaceholderText("∠x")
        self.input_x_angle.textChanged.connect(self.x_angle_chosen)

        self.input_y_angle = QLineEdit()
        self.input_y_angle.setPlaceholderText("∠y")
        self.input_y_angle.textChanged.connect(self.y_angle_chosen)

        self.camera_button = QPushButton("Включить камеру")
        self.camera_button.clicked.connect(self.camera_button_clicked)

        self.start_button = QPushButton("Установить углы")
        self.start_button.clicked.connect(self.start_button_clicked)

        layout = QVBoxLayout()
        widgets = [
            com_port_selector,
            input_pwm_max_voltage,
            scale_factor_selector,
            self.input_x_angle,
            self.input_y_angle,
            self.camera_button,
            self.start_button
        ]

        for widget in widgets:
            layout.addWidget(widget)

        widget = QWidget()
        widget.setLayout(layout)

        self.setCentralWidget(widget)

    def pwm_max_voltage_chosen(self, i):
        self.pwm_max_voltage = i

    def scale_factor_chosen(self, i):
        self.scale_factor = float(self.scale_factors[i])

    def x_angle_chosen(self, i):
        self.x_angle = i

    def y_angle_chosen(self, i):
        self.y_angle = i

    def camera_button_clicked(self):
        if self.camera_widget is None:
            self.camera_button.setText('Выключить камеру')
            self.camera_widget = CameraWindow()
            self.camera_widget.show()
        else:
            self.camera_button.setText('Включить камеру')
            self.camera_widget.close()
            self.camera_widget = None

    def start_button_clicked(self):
        scale_factor = float(self.scale_factor)
        t_x_angle = float(self.x_angle)
        t_y_angle = float(self.y_angle)
        t_pwm_max_voltage = int(self.pwm_max_voltage)

        x_target_voltage = target_voltage(t_x_angle, scale_factor)
        y_target_voltage = target_voltage(t_y_angle, scale_factor)

        ser = serial.Serial(self.com_port, 115200)
        send_command(ser, x_target_voltage, y_target_voltage)
        ser.close()


def main():
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == '__main__':
    # 0.2x0.    2мм
    # pattern = r"\d\W\d{1,5}"
    #main()

    '''ser = serial.Serial('COM3', 115200)
    
    serial.write(
        f"{voltage_to_duty_cycle(x_voltage)}|{voltage_to_duty_cycle(y_voltage)}F".encode()
    )'''

    volt_x = target_voltage(0.0, 0.8)
    volt_x_1 = voltage_centralization(volt_x)
    volt_y = target_voltage(0.0, 0.8)
    volt_y_1 = voltage_centralization(volt_y)

    print(volt_x_1, volt_y_1)

    volt_x_2 = voltage_to_duty_cycle(volt_x_1)
    volt_y_2 = voltage_to_duty_cycle(volt_y_1)

    ser = serial.Serial('COM3', 115200)

    print(f"{volt_x_2}|{volt_y_2}F".encode())

    ser.write(
        f"{volt_x_2}|{volt_y_2}F".encode()
    )


    def quant_level(value: str) -> int:
        temp = ''
        for s in value:
            try:
                temp += str(int(s))
            except ValueError:
                pass
        return int(temp)


    def to_voltage(value: str) -> float:
        level = quant_level(value)
        return float(3.3 / 4096 * level * 11.2)

    while 1:
        t = ser.read(6).decode()
        print(t, to_voltage(t))





