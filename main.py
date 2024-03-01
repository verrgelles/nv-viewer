import serial.tools.list_ports
from PyQt5.QtMultimedia import QCameraInfo, QCamera
from PyQt5.QtMultimediaWidgets import QCameraViewfinder
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QMainWindow, QLineEdit, QPushButton, QComboBox, QLabel, \
    QGridLayout

import pandas as pd
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
    return float(3.3/4096*q_level*11.2)

class CameraWindow(QWidget):
    def __init__(self):
        super(CameraWindow, self).__init__()

        self.setWindowTitle("\n")

        self.camera = None

        layout = QVBoxLayout()

        cameras = QCameraInfo.availableCameras()

        for camera in cameras:
            if camera.description() == 'HB-500':
                self.camera = camera

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

def debug():
    volt_x = target_voltage(0.0, 0.8)
    volt_x_1 = voltage_centering(volt_x)
    volt_y = target_voltage(0.0, 0.8)
    volt_y_1 = voltage_centering(volt_y)

    print(volt_x_1, volt_y_1)

    volt_x_2 = voltage_to_duty_cycle(volt_x_1)
    volt_y_2 = voltage_to_duty_cycle(volt_y_1)

    ser = serial.Serial('COM3', 115200)

    print(f"{volt_x_2}|{volt_y_2}F".encode())

    ser.write(
        f"{volt_x_2}|{volt_y_2}F".encode()
    )

    while 1:
        t = ser.read(6).decode()
        print(t, callback_to_voltage(t))

if __name__ == '__main__':
    main()

