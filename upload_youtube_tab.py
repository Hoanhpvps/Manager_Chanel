# PyQt5 Imports
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog,
    QSizePolicy, QRadioButton, QButtonGroup, QLineEdit, QListWidget,
    QProgressBar, QFrame, QComboBox, QScrollArea, QMessageBox, QCheckBox,
    QGroupBox, QTextEdit, QDateEdit, QSpinBox, QDialog, 
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDate, QTimer
from PyQt5.QtGui import QDragEnterEvent, QDropEvent

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys

from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, StaleElementReferenceException,
    ElementNotInteractableException, ElementClickInterceptedException,
    UnexpectedAlertPresentException, InvalidSelectorException, WebDriverException
)
from webdriver_manager.chrome import ChromeDriverManager

# Standard Library Imports
import os
import json
import time
import psutil
import re
import requests
import zipfile
import io
import traceback
from subprocess import CREATE_NO_WINDOW
import win32api
from PyQt5.QtWidgets import QInputDialog, QMessageBox
from PyQt5.QtCore import Qt
from PyQt5.QtCore import QEventLoop
from .selectors import YouTubeSelectors as YTS


class UploadWorker(QThread):
    progress_updated = pyqtSignal(int, str)
    upload_complete = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, channel_frame):
        super().__init__()
        self.channel_frame = channel_frame
    
    def cleanup_driver(self):
        try:
            if hasattr(self, 'driver') and self.driver:
                self.driver.quit()
        except Exception as e:
            print(f"Error cleaning up driver: {e}")

    def close_webdriver_processes(self):
        try:
                for process in psutil.process_iter(['pid', 'name']):
                    # Only target chromedriver.exe and geckodriver.exe
                    if process.info['name'] in ['chromedriver.exe', 'geckodriver.exe']:
                        psutil.Process(process.info['pid']).terminate()
                time.sleep(2)
        except Exception as e:
            print(f"Error closing WebDriver processes: {e}")

    def run(self):
        try:
            self.close_webdriver_processes()
            if self.channel_frame.firefox_radio.isChecked():
                self.setup_firefox_driver()
            else:
                self.setup_chrome_driver()
                
            self.perform_upload()
            
        except Exception as e:
            self.error_occurred.emit(str(e))

    def setup_firefox_driver(self):
        selected_profile = self.channel_frame.profile_combo.currentText()
        profile_id = self.channel_frame.profiles_dict[selected_profile]
        profile_path = os.path.expanduser(f'~\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles\\{profile_id}')
        
        firefox_options = webdriver.FirefoxOptions()
        firefox_options.binary_location = r"C:/Program Files/Mozilla Firefox/firefox.exe"
        firefox_options.add_argument("-profile")
        firefox_options.add_argument(os.fspath(profile_path))
        
        self.driver = webdriver.Firefox(options=firefox_options)
        self.driver.set_window_size(1320, 960)

    def get_chrome_version(self, chrome_path):
        try:
            chrome_dir = os.path.dirname(chrome_path)
            chrome_exe = os.path.join(chrome_dir, 'App', 'Chrome-bin', 'chrome.exe')
            version_info = win32api.GetFileVersionInfo(chrome_exe, '\\')
            ms = version_info['FileVersionMS']
            ls = version_info['FileVersionLS']
            version = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
            return version
        except Exception as e:
            print(f"Version detection error: {str(e)}")
            return None

    def setup_chrome_driver(self):
        try:
            chrome_path = self.channel_frame.chrome_path_edit.text().strip()
            
            # Add initial delay for stability
            time.sleep(2)
            
            chrome_version = self.get_chrome_version(chrome_path)
            if not chrome_version:
                raise Exception("Unable to detect Chrome version")
                
            options = webdriver.ChromeOptions()
            options.binary_location = chrome_path
            
            # Add additional stability options
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--remote-debugging-port=9222')
            options.add_argument('--start-maximized')
            options.page_load_strategy = 'normal'
            
            data_dir = os.path.join(os.path.dirname(chrome_path), 'Data')
            if os.path.exists(data_dir):
                options.add_argument(f'--user-data-dir={data_dir}')
            
            driver_path = ChromeDriverManager(driver_version=chrome_version).install()
            service = Service(executable_path=driver_path)
            service.creation_flags = CREATE_NO_WINDOW
            
            # Add retry mechanism
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.driver = webdriver.Chrome(service=service, options=options)
                    self.driver.set_window_size(1320, 960)
                    # Test driver by executing simple command
                    self.driver.execute_script('return document.readyState')
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise e
                    time.sleep(2)
                    
        except Exception as e:
            raise Exception(f"Failed to setup Chrome: {str(e)}")

    def download_chromedriver(self, chrome_version):
        try:
            # Create storage directory
            user_home = os.path.expanduser('~')
            chromedriver_dir = os.path.join(user_home, 'AppData', 'Local', 'ChromeDriver')
            os.makedirs(chromedriver_dir, exist_ok=True)
            
            # Extract major version from Chrome Portable
            major_version = chrome_version.split('.')[0]
            
            # Set driver version based on Chrome version
            driver_version_map = {
                "129": "129.0.6668.59",
                "128": "128.0.6462.59",
                # Add more versions as needed
            }
            
            driver_version = driver_version_map.get(major_version)
            if not driver_version:
                raise Exception(f"Unsupported Chrome version: {major_version}")
                
            # Download matching ChromeDriver
            driver_path = ChromeDriverManager(driver_version=driver_version).install()
            
            # Move to our managed location
            final_path = os.path.join(chromedriver_dir, f"chromedriver_{major_version}.exe")
            shutil.copy2(driver_path, final_path)
            
            return final_path
            
        except Exception as e:
            raise Exception(f"ChromeDriver download failed: {str(e)}")

    def find_existing_chromedriver(self, driver_dir, chrome_version):
        try:
            for root, dirs, files in os.walk(driver_dir):
                if 'chromedriver.exe' in files:
                    driver_path = os.path.join(root, 'chromedriver.exe')
                    # Verify driver version matches Chrome version
                    import subprocess
                    output = subprocess.check_output([driver_path, '--version']).decode()
                    if f"ChromeDriver {chrome_version}." in output:
                        return driver_path
            return None
        except:
            return None

    def perform_upload(self):
        try:
            wait = WebDriverWait(self.driver, 15)
            self.driver.get("https://studio.youtube.com")
            time.sleep(5)

            # Check login status
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            if "Sign in" in self.driver.page_source:
                self.error_occurred.emit("Not logged in")
                return False

            # Click create button
            create_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//ytcp-button[@id="create-icon"]')))
            create_button.click()
            time.sleep(2)

            # Click upload button 
            upload_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//tp-yt-paper-item[@id="text-item-0"]')))
            upload_button.click()
            time.sleep(2)

            # Prepare video paths and upload
            video_paths = []
            for i in range(self.channel_frame.video_list.count()):
                file_path = self.channel_frame.video_list.item(i).text()
                normalized_path = os.path.abspath(file_path).replace('/', '\\')
                video_paths.append(normalized_path)

            # Upload files
            file_input = wait.until(EC.presence_of_element_located((By.XPATH, '//input[@type="file"]')))
            file_input.send_keys('\n'.join(video_paths))
            
            # Wait for upload progress monitor to appear
            time.sleep(5)
            
            while True:
                try:
                    # Check for upload progress header
                    progress_header = wait.until(EC.presence_of_element_located(
                        (By.CLASS_NAME, "header.style-scope.ytcp-multi-progress-monitor")
                    ))
                    
                    # Get upload count status
                    count_element = progress_header.find_element(By.CLASS_NAME, "count.style-scope.ytcp-multi-progress-monitor")
                    count_text = count_element.text
                    self.progress_updated.emit(50, f"Uploading: {count_text}")
                    
                    # Check for remaining time
                    try:
                        eta_element = self.driver.find_element(By.ID, "eta")
                        if eta_element.is_displayed():
                            eta_text = eta_element.text
                            self.progress_updated.emit(75, f"Uploading: {count_text} - {eta_text}")
                    except:
                        pass
                    
                    # Check if upload is complete and close button is available
                    try:
                        close_button = self.driver.find_element(
                            By.XPATH, 
                            '//ytcp-icon-button[@id="close-button" and contains(@class, "style-scope ytcp-multi-progress-monitor")]'
                        )
                        if close_button.is_displayed():
                            self.progress_updated.emit(100, "Upload complete!")
                            close_button.click()
                            time.sleep(2)  # Wait for dialog to close
                            self.upload_complete.emit()
                            return True
                    except:
                        pass
                    
                    time.sleep(1)
                    
                except StaleElementReferenceException:
                    time.sleep(1)
                    continue
                except Exception as e:
                    self.error_occurred.emit(f"Error monitoring upload progress: {str(e)}")
                    return False

        except Exception as e:
            self.error_occurred.emit(str(e))
            return False
        finally:
            if self.driver:
                self.driver.quit()

class ChannelFrame(QFrame):
    def __init__(self, channel_name):
        super().__init__()
        self.anti_bq_manager = AntiBQManagerDialog(self)
        self.setFrameStyle(QFrame.StyledPanel)
        self.video_files = []
        self.profiles_dict = {}
        self.chrome_path = ""
        self.remove_after_upload = False
        self.is_browser_hidden = False  # Thêm biến theo dõi trạng thái ẩn/hiện
        self.init_channel_ui(channel_name)
        # The parent tab will handle loading profiles

    def start_anti_bq(self):
        # Initialize anti-BQ queue
        self.anti_bq_queue = []
        
        # Add all selected channel frames to queue
        for channel_frame in self.channel_frames:
            if channel_frame.anti_bq_function.isChecked():
                self.anti_bq_queue.append(channel_frame)
                
        # Start processing if queue is not empty    
        if self.anti_bq_queue:
            self.process_next_anti_bq()

    
    def show_anti_bq_manager(self):
        self.anti_bq_manager.exec_()

    def toggle_browser_visibility(self):
        if hasattr(self, 'anti_bq_worker') and self.anti_bq_worker and self.anti_bq_worker.driver:
            try:
                if self.anti_bq_worker.is_browser_hidden:
                    # Hiện trình duyệt
                    self.anti_bq_worker.driver.set_window_position(0, 0)
                    self.anti_bq_worker.is_browser_hidden = False
                    self.toggle_browser_btn.setText("Ẩn trình duyệt")
                else:
                    # Ẩn trình duyệt
                    self.anti_bq_worker.driver.set_window_position(-3000, 0)
                    self.anti_bq_worker.is_browser_hidden = True
                    self.toggle_browser_btn.setText("Hiện trình duyệt")
                return True
            except Exception as e:
                print(f"Error toggling browser visibility: {str(e)}")
                return False
        return False


    action_type_changed = pyqtSignal()
    def init_channel_ui(self, channel_name):
        main_layout = QHBoxLayout()  

        # Left Panel - Video List
        left_panel = QVBoxLayout()
        
        # Video list
        self.video_list = DragDropListWidget(self)
        self.video_list.setMinimumHeight(250)
        self.video_list.setMinimumWidth(300)
        self.video_list.setAcceptDrops(True)
        self.video_list.setDragEnabled(True)
        
        # Video controls
        video_controls = QHBoxLayout()
        add_video_btn = QPushButton("Thêm Video")
        remove_video_btn = QPushButton("Xóa Video")
        self.remove_videos_cb = QCheckBox("Xóa sau khi upload")
        
        video_controls.addWidget(add_video_btn)
        video_controls.addWidget(remove_video_btn)
        video_controls.addWidget(self.remove_videos_cb)
        
        add_video_btn.clicked.connect(self.add_videos)
        remove_video_btn.clicked.connect(self.remove_video)
        self.remove_videos_cb.toggled.connect(self.toggle_remove_videos)
        
        left_panel.addWidget(QLabel("Danh sách video:"))
        left_panel.addWidget(self.video_list)
        left_panel.addLayout(video_controls)

        # Right Panel - Settings
        right_panel = QVBoxLayout()
        
        # Channel header
        header = QLabel(f"Kênh: {channel_name}")
        header.setStyleSheet("font-weight: bold;")
        
        # Function selection group
        function_group = QGroupBox("Chọn chức năng")
        function_layout = QHBoxLayout()
        self.function_type = QButtonGroup()
        self.upload_function = QRadioButton("Upload video")
        self.anti_bq_function = QRadioButton("Kháng BQ video")
        self.function_type.addButton(self.upload_function)
        self.function_type.addButton(self.anti_bq_function)
        self.upload_function.setChecked(True)
        function_layout.addWidget(self.upload_function)
        function_layout.addWidget(self.anti_bq_function)
        function_group.setLayout(function_layout)

        # Upload Frame (contains all upload-related options)
        self.upload_frame = QFrame()
        upload_layout = QVBoxLayout()
        
        # Browser selection
        browser_group = QGroupBox("Chọn trình duyệt")
        browser_layout = QVBoxLayout()
        self.browser_type = QButtonGroup()
        self.firefox_radio = QRadioButton("Firefox")
        self.chrome_radio = QRadioButton("Chrome Portable")
        self.browser_type.addButton(self.firefox_radio)
        self.browser_type.addButton(self.chrome_radio)
        browser_layout.addWidget(self.firefox_radio)
        browser_layout.addWidget(self.chrome_radio)
        browser_group.setLayout(browser_layout)
        self.firefox_radio.setChecked(True)
        
        # Profile/Chrome selection frames
        self.profile_frame = QFrame()
        profile_layout = QVBoxLayout()
        self.profile_combo = QComboBox()
        self.check_profile_btn = QPushButton("Kiểm tra Profile")
        profile_layout.addWidget(QLabel("Profile:"))
        profile_layout.addWidget(self.profile_combo)
        profile_layout.addWidget(self.check_profile_btn)
        self.profile_frame.setLayout(profile_layout)
        
        self.chrome_frame = QFrame()
        chrome_layout = QVBoxLayout()
        self.chrome_path_edit = QLineEdit()
        self.chrome_select_btn = QPushButton("Chọn File Chrome")
        chrome_layout.addWidget(self.chrome_path_edit)
        chrome_layout.addWidget(self.chrome_select_btn)
        self.chrome_frame.setLayout(chrome_layout)
        self.chrome_frame.hide()
        
        # Add components to upload layout
        upload_layout.addWidget(browser_group)
        upload_layout.addWidget(self.profile_frame)
        upload_layout.addWidget(self.chrome_frame)

        # Set layout for upload frame
        self.upload_frame.setLayout(upload_layout)

        self.action_type_group = QGroupBox("Kiểu Thao Tác")  # Store as instance variable
        action_type_layout = QVBoxLayout()
        self.action_type = QButtonGroup()
        self.upload_action = QRadioButton("Tiến hành Upload")
        self.edit_info_action = QRadioButton("Sửa thông tin video")
        self.edit_status_action = QRadioButton("Sửa trạng thái video")
        self.action_type.addButton(self.upload_action)
        self.action_type.addButton(self.edit_info_action)
        self.action_type.addButton(self.edit_status_action)
        self.upload_action.setChecked(True)
        action_type_layout.addWidget(self.upload_action)
        action_type_layout.addWidget(self.edit_info_action)
        action_type_layout.addWidget(self.edit_status_action)
        self.action_type_group.setLayout(action_type_layout)

        # Frame cho sửa thông tin video
        self.edit_info_frame = QFrame()
        edit_info_layout = QVBoxLayout()

        # Tiêu đề video
        title_group = QGroupBox("Tiêu đề video")
        title_layout = QVBoxLayout()
        self.title_edit = QTextEdit()
        self.title_edit.setPlaceholderText("Nhập danh sách tiêu đề (mỗi dòng một tiêu đề)")
        title_layout.addWidget(self.title_edit)
        title_group.setLayout(title_layout)

        # Mô tả video
        desc_group = QGroupBox("Mô tả video")
        desc_layout = QVBoxLayout()
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Nhập mô tả (sử dụng {title} để chèn tiêu đề)")
        desc_layout.addWidget(self.desc_edit)
        desc_group.setLayout(desc_layout)

        # Tags
        tags_group = QGroupBox("Thẻ tag")
        tags_layout = QVBoxLayout()
        self.tags_edit = QTextEdit()
        self.tags_edit.setPlaceholderText("Nhập các từ khóa, phân cách bằng dấu phẩy")
        self.random_tags_cb = QCheckBox("Random tags (tối đa 500 ký tự)")
        tags_layout.addWidget(self.tags_edit)
        tags_layout.addWidget(self.random_tags_cb)
        tags_group.setLayout(tags_layout)

        # Thumbnail
        thumb_group = QGroupBox("Ảnh thumbnail")
        thumb_layout = QHBoxLayout()
        self.thumb_path_edit = QLineEdit()
        self.thumb_select_btn = QPushButton("Chọn thư mục")
        thumb_layout.addWidget(self.thumb_path_edit)
        thumb_layout.addWidget(self.thumb_select_btn)
        thumb_group.setLayout(thumb_layout)

        edit_info_layout.addWidget(title_group)
        edit_info_layout.addWidget(desc_group)
        edit_info_layout.addWidget(tags_group)
        edit_info_layout.addWidget(thumb_group)
        self.edit_info_frame.setLayout(edit_info_layout)
        self.edit_info_frame.hide()

        # Frame cho sửa trạng thái video
        self.edit_status_frame = QFrame()
        edit_status_layout = QVBoxLayout()

        # Radio buttons cho trạng thái
        status_group = QGroupBox("Trạng thái")
        status_layout = QVBoxLayout()
        self.status_type = QButtonGroup()
        self.schedule_radio = QRadioButton("Đặt lịch")
        self.public_radio = QRadioButton("Public")
        self.status_type.addButton(self.schedule_radio)
        self.status_type.addButton(self.public_radio)
        self.schedule_radio.setChecked(True)
        status_layout.addWidget(self.schedule_radio)
        status_layout.addWidget(self.public_radio)
        status_group.setLayout(status_layout)

        # Thời gian
        time_group = QGroupBox("Thời gian")
        time_layout = QVBoxLayout()
        self.time_edit = QLineEdit()
        self.time_edit.setPlaceholderText("hh:mm,hh:mm,hh:mm")
        time_layout.addWidget(self.time_edit)
        time_group.setLayout(time_layout)

        # Ngày tháng
        date_group = QGroupBox("Ngày tháng")
        date_layout = QVBoxLayout()
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        date_layout.addWidget(self.date_edit)
        date_group.setLayout(date_layout)

        # Số video xử lý
        video_count_group = QGroupBox("Số video cần xử lý")
        video_count_layout = QVBoxLayout()
        self.video_count_spin = QSpinBox()
        self.video_count_spin.setMinimum(1)
        video_count_layout.addWidget(self.video_count_spin)
        video_count_group.setLayout(video_count_layout)

        edit_status_layout.addWidget(status_group)
        edit_status_layout.addWidget(time_group)
        edit_status_layout.addWidget(date_group)
        edit_status_layout.addWidget(video_count_group)
        self.edit_status_frame.setLayout(edit_status_layout)
        self.edit_status_frame.hide()



        # Anti BQ Frame
        self.anti_bq_frame = QFrame()
        anti_bq_layout = QVBoxLayout()
        
        # Browser selection for Anti-BQ
        anti_bq_browser_group = QGroupBox("Chọn trình duyệt")
        anti_bq_browser_layout = QVBoxLayout()
        self.anti_bq_browser_type = QButtonGroup()
        self.anti_bq_firefox_radio = QRadioButton("Firefox")
        self.anti_bq_chrome_radio = QRadioButton("Chrome Portable")
        self.anti_bq_browser_type.addButton(self.anti_bq_firefox_radio)
        self.anti_bq_browser_type.addButton(self.anti_bq_chrome_radio)
        anti_bq_browser_layout.addWidget(self.anti_bq_firefox_radio)
        anti_bq_browser_layout.addWidget(self.anti_bq_chrome_radio)
        anti_bq_browser_group.setLayout(anti_bq_browser_layout)
        self.anti_bq_firefox_radio.setChecked(True)
        
        # Profile/Chrome selection frames for Anti-BQ
        self.anti_bq_profile_frame = QFrame()
        anti_bq_profile_layout = QVBoxLayout()
        self.anti_bq_profile_combo = QComboBox()
        self.anti_bq_check_profile_btn = QPushButton("Kiểm tra Profile")
        anti_bq_profile_layout.addWidget(QLabel("Profile:"))
        anti_bq_profile_layout.addWidget(self.anti_bq_profile_combo)
        anti_bq_profile_layout.addWidget(self.anti_bq_check_profile_btn)
        self.anti_bq_profile_frame.setLayout(anti_bq_profile_layout)
        
        self.anti_bq_chrome_frame = QFrame()
        anti_bq_chrome_layout = QVBoxLayout()
        self.anti_bq_chrome_path_edit = QLineEdit()
        self.anti_bq_chrome_select_btn = QPushButton("Chọn File Chrome")
        anti_bq_chrome_layout.addWidget(self.anti_bq_chrome_path_edit)
        anti_bq_chrome_layout.addWidget(self.anti_bq_chrome_select_btn)
        self.anti_bq_chrome_frame.setLayout(anti_bq_chrome_layout)
        self.anti_bq_chrome_frame.hide()
        
        # Content management button
        manage_content_btn = QPushButton("Quản lý nội dung kháng BQ")
        
        # Add components to Anti-BQ layout
        anti_bq_layout.addWidget(anti_bq_browser_group)
        anti_bq_layout.addWidget(self.anti_bq_profile_frame)
        anti_bq_layout.addWidget(self.anti_bq_chrome_frame)
        anti_bq_layout.addWidget(manage_content_btn)
        
        self.anti_bq_frame.setLayout(anti_bq_layout)
        self.anti_bq_frame.hide()
        
        # Thêm nút toggle sau nút "Quản lý nội dung kháng BQ"
        self.toggle_browser_btn = QPushButton("Ẩn/Hiện trình duyệt")
        self.toggle_browser_btn.clicked.connect(self.toggle_browser_visibility)
        self.toggle_browser_btn.setEnabled(False)  # Mặc định disable cho đến khi có driver
        
        # Thêm nút vào layout
        anti_bq_layout.addWidget(self.toggle_browser_btn)  # Thay your_layout bằng layout thực tế

        # Connect additional signals
        self.anti_bq_firefox_radio.toggled.connect(self.toggle_anti_bq_browser_options)
        self.anti_bq_chrome_select_btn.clicked.connect(self.select_anti_bq_chrome)
        self.anti_bq_check_profile_btn.clicked.connect(self.open_anti_bq_profile_for_check)
        manage_content_btn.clicked.connect(self.show_anti_bq_manager)


        # Connect signals
        self.firefox_radio.toggled.connect(self.toggle_browser_options)
        self.chrome_select_btn.clicked.connect(self.select_chrome)
        self.check_profile_btn.clicked.connect(self.open_profile_for_check)
        self.upload_function.toggled.connect(self.toggle_function_frames)

        # Trong init_channel_ui
        self.upload_action.toggled.connect(self.on_action_type_changed)
        self.edit_info_action.toggled.connect(self.on_action_type_changed)
        self.edit_status_action.toggled.connect(self.on_action_type_changed)
        self.upload_action.toggled.connect(self.toggle_action_frames)
        self.edit_info_action.toggled.connect(self.toggle_action_frames)
        self.edit_status_action.toggled.connect(self.toggle_action_frames)
        self.thumb_select_btn.clicked.connect(self.select_thumb_folder)

        # Add components to right panel
        right_panel.addWidget(header)
        right_panel.addWidget(function_group)
        right_panel.addWidget(self.action_type_group)
        right_panel.addWidget(self.upload_frame)
        right_panel.addWidget(self.edit_info_frame)  # Thêm frame sửa thông tin
        right_panel.addWidget(self.edit_status_frame)  # Thêm frame sửa trạng thái
        right_panel.addWidget(self.anti_bq_frame)
        right_panel.addStretch()

        # Add panels to main layout
        main_layout.addLayout(left_panel, stretch=40)
        main_layout.addLayout(right_panel, stretch=60)
        
        self.setLayout(main_layout)

    def on_action_type_changed(self):
        self.action_type_changed.emit()

    def toggle_action_frames(self):
        if self.upload_action.isChecked():
            self.video_list.setEnabled(True)
            self.edit_info_frame.hide()
            self.edit_status_frame.hide()
        elif self.edit_info_action.isChecked():
            self.video_list.setEnabled(False)
            self.edit_info_frame.show()
            self.edit_status_frame.hide()
        else:  # edit_status_action
            self.video_list.setEnabled(False)
            self.edit_info_frame.hide()
            self.edit_status_frame.show()

    def select_thumb_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa ảnh thumbnail")
        if folder:
            self.thumb_path_edit.setText(folder)\

    def show_input_dialog(self, title, message):
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(message)
        dialog.resize(500, 200)
        
        if dialog.exec_() == QDialog.Accepted:
            self.current_worker.input_text = dialog.textValue()
            self.current_worker.input_received.emit(dialog.textValue())
        else:
            self.current_worker.input_text = None
            self.current_worker.input_received.emit("")

    def show_confirmation_dialog(self, title, message):
        reply = QMessageBox.question(self, title, message,
                                   QMessageBox.Yes | QMessageBox.No)
        result = reply == QMessageBox.Yes
        self.current_worker.confirmation_result = result
        self.current_worker.confirmation_received.emit(result)

    def setup_anti_bq_worker(self):
        self.anti_bq_worker = AntiBQWorker(self)
        
        # Connect dialog signals
        self.anti_bq_worker.show_input_dialog.connect(self.show_input_dialog)
        self.anti_bq_worker.show_question_dialog.connect(self.show_question_dialog)

    def show_question_dialog(self, title, message):
        # Ensure dialog runs in main thread
        reply = QMessageBox.question(None, title, message,
                                   QMessageBox.Yes | QMessageBox.No)
        return reply == QMessageBox.Yes

    def toggle_anti_bq_browser_options(self, checked):
        if checked:
            self.anti_bq_profile_frame.show()
            self.anti_bq_chrome_frame.hide()
        else:
            self.anti_bq_profile_frame.hide()
            self.anti_bq_chrome_frame.show()

    def select_anti_bq_chrome(self):
        file_path = QFileDialog.getOpenFileName(
            self,
            "Select Chrome Portable",
            "",
            "Executable files (*.exe)"
        )[0]
        if file_path:
            self.anti_bq_chrome_path_edit.setText(file_path)

    def open_anti_bq_profile_for_check(self):
        if self.anti_bq_firefox_radio.isChecked():
            selected_profile = self.anti_bq_profile_combo.currentText()
            if selected_profile in self.profiles_dict:
                profile_id = self.profiles_dict[selected_profile]
                self.close_existing_firefox()
                
                try:
                    firefox_options = webdriver.FirefoxOptions()
                    firefox_options.binary_location = r"C:/Program Files/Mozilla Firefox/firefox.exe"
                    profile_path = os.path.expanduser(f'~\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles\\{profile_id}')
                    firefox_options.add_argument("-profile")
                    firefox_options.add_argument(os.fspath(profile_path))
                    
                    driver = webdriver.Firefox(options=firefox_options)
                    driver.get("https://studio.youtube.com")
                    QMessageBox.information(self, "Thông báo", 
                        "Profile đã được mở. Hãy kiểm tra và đóng trình duyệt khi hoàn tất!")
                except Exception as e:
                    QMessageBox.warning(self, "Lỗi", f"Không thể mở profile: {str(e)}")
        else:
            QMessageBox.information(self, "Thông báo", 
                "Tính năng này chỉ khả dụng cho Firefox!")

    def start_anti_bq(self):
        if self.video_list.count() == 0:
            QMessageBox.warning(self, "Lỗi", "Vui lòng thêm video trước khi kháng BQ!")
            return
            
        self.anti_bq_worker = AntiBQWorker(self)
        self.anti_bq_worker.progress_updated.connect(self.update_progress)
        self.anti_bq_worker.process_complete.connect(self.on_anti_bq_complete)
        self.anti_bq_worker.error_occurred.connect(self.on_anti_bq_error)
        self.anti_bq_worker.start()

    def on_anti_bq_complete(self):
        QMessageBox.information(self, "Thành công", "Đã hoàn thành kháng BQ!")
        
    def on_anti_bq_error(self, error_message):
        QMessageBox.warning(self, "Lỗi", f"Lỗi khi kháng BQ: {error_message}")

    def toggle_function_frames(self, checked):
        if self.upload_function.isChecked():
            self.upload_frame.show()
            self.anti_bq_frame.hide()
            # Show action type group và các frame liên quan
            self.action_type_group.show()
            self.edit_info_frame.setVisible(self.edit_info_action.isChecked())
            self.edit_status_frame.setVisible(self.edit_status_action.isChecked())
        else:  # anti_bq_function được chọn
            self.upload_frame.hide()
            self.anti_bq_frame.show()
            # Hide action type group và tất cả các frame liên quan
            self.action_type_group.hide()
            self.edit_info_frame.hide()
            self.edit_status_frame.hide()

    def show_anti_bq_manager(self):
        dialog = AntiBQManagerDialog(self)
        dialog.exec_()

    def toggle_remove_videos(self, checked):
        self.remove_after_upload = checked

    def open_profile_for_check(self):
        if self.firefox_radio.isChecked():
            selected_profile = self.profile_combo.currentText()
            if selected_profile in self.profiles_dict:
                profile_id = self.profiles_dict[selected_profile]
                self.close_existing_firefox()
                
                try:
                    firefox_options = webdriver.FirefoxOptions()
                    firefox_options.binary_location = r"C:/Program Files/Mozilla Firefox/firefox.exe"
                    profile_path = os.path.expanduser(f'~\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles\\{profile_id}')
                    firefox_options.add_argument("-profile")
                    firefox_options.add_argument(os.fspath(profile_path))
                    
                    driver = webdriver.Firefox(options=firefox_options)
                    driver.get("https://studio.youtube.com")
                    QMessageBox.information(self, "Thông báo", 
                        "Profile đã được mở. Hãy kiểm tra và đóng trình duyệt khi hoàn tất!")
                except Exception as e:
                    QMessageBox.warning(self, "Lỗi", f"Không thể mở profile: {str(e)}")
        else:
            QMessageBox.information(self, "Thông báo", 
                "Tính năng này chỉ khả dụng cho Firefox!")

    def close_existing_firefox(self):
        for process in psutil.process_iter(['pid', 'name']):
            try:
                if process.info['name'] == 'firefox.exe':
                    psutil.Process(process.info['pid']).terminate()
                    time.sleep(1)  # Đợi process đóng hoàn toàn
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            for url in urls:
                file_path = url.toLocalFile()
                if file_path.lower().endswith(('.mp4', '.avi', '.mkv')):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        files = [url.toLocalFile() for url in event.mimeData().urls()]
        self.add_files_to_list(files)
        event.acceptProposedAction()

    def toggle_browser_options(self):
        if self.firefox_radio.isChecked():
            self.chrome_frame.hide()
            self.profile_frame.show()
        else:
            self.profile_frame.hide()
            self.chrome_frame.show()

    def select_chrome(self):
        file_path = QFileDialog.getOpenFileName(
            self,
            "Select Chrome Portable",
            "",
            "Executable files (*.exe)"
        )[0]
        if file_path:
            self.chrome_path_edit.setText(file_path)

    def add_files_to_list(self, files):
        valid_extensions = ('.mp4', '.avi', '.mkv')
        for file_path in files:
            if file_path.lower().endswith(valid_extensions):
                normalized_path = os.path.abspath(file_path).replace('/', '\\')
                existing_items = [self.video_list.item(i).text() 
                                for i in range(self.video_list.count())]
                if normalized_path not in existing_items:
                    self.video_list.addItem(normalized_path)

    def add_videos(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Videos",
            "",
            "Video files (*.mp4 *.avi *.mkv)"
        )
        self.add_files_to_list(files)
    
    def remove_video(self):
        current_row = self.video_list.currentRow()
        if current_row >= 0:
            self.video_list.takeItem(current_row)

    def process_next_edit_info(self):
        if self.upload_queue:
            channel_frame = self.upload_queue[0]
            editor = EditVideoInfo(channel_frame.driver, self.update_progress)
            try:
                results = editor.start_edit_process()
                # Xử lý kết quả
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", f"Lỗi khi sửa thông tin: {str(e)}")
            finally:
                self.upload_queue.pop(0)
                if self.upload_queue:
                    self.process_next_edit_info()

    def process_next_edit_status(self):
        if self.upload_queue:
            channel_frame = self.upload_queue[0]
            editor = EditVideoStatus(channel_frame.driver, self.update_progress)
            try:
                results = editor.start_edit_process()
                # Xử lý kết quả
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", f"Lỗi khi sửa trạng thái: {str(e)}")
            finally:
                self.upload_queue.pop(0)
                if self.upload_queue:
                    self.process_next_edit_status()

class UploadYoutubeTab(QWidget):
    progress_updated = pyqtSignal(int, str)  # Add this signal
    def __init__(self):
        super().__init__()
        self.upload_queue = []  # Hàng đợi upload
        self.current_worker = None
        self.current_channel_frame = None  # Add this line
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.channel_frames = []
        self.anti_bq_queue = []  # Thêm queue cho kháng BQ
        self.init_upload_ui()
        self.load_firefox_profiles()
        # Connect the signal to update progress bar
        self.progress_updated.connect(self.update_progress)

    def init_upload_ui(self):
        main_layout = QVBoxLayout()
        
        # Scroll area for channels
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        self.channels_layout = QVBoxLayout(scroll_content)
        
        # Add first channel
        self.add_channel()
        
        scroll.setWidget(scroll_content)
        
        # Control buttons
        controls = QHBoxLayout()
        add_channel_btn = QPushButton("Thêm Kênh Mới")
        self.upload_all_btn = QPushButton("Upload Tất Cả")  # Store as instance variable
        anti_bq_all_btn = QPushButton("Kháng BQ Tất Cả")
        
        controls.addWidget(add_channel_btn)
        controls.addWidget(self.upload_all_btn)  # Use instance variable
        controls.addWidget(anti_bq_all_btn)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.status_label = QLabel()
        
        # Add components to main layout
        main_layout.addWidget(scroll)
        main_layout.addLayout(controls)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.status_label)
        
        self.setLayout(main_layout)
        
        # Connect signals
        add_channel_btn.clicked.connect(self.add_channel)
        self.upload_all_btn.clicked.connect(self.start_upload_all)  # Use instance variable
        anti_bq_all_btn.clicked.connect(self.start_anti_bq)

    def start_anti_bq(self):
        # Initialize anti-BQ queue
        self.anti_bq_queue = []
        
        # Use channel_frames list instead of channel_tabs
        for channel_frame in self.channel_frames:
            if channel_frame.anti_bq_function.isChecked():
                self.anti_bq_queue.append(channel_frame)
                
        if self.anti_bq_queue:
            self.process_next_anti_bq()
        else:
            QMessageBox.information(self, "Thông báo", "Không có kênh nào để xử lý!")

    def get_chrome_version(self, chrome_path):
        try:
            chrome_dir = os.path.dirname(chrome_path)
            chrome_exe = os.path.join(chrome_dir, 'App', 'Chrome-bin', 'chrome.exe')
            version_info = win32api.GetFileVersionInfo(chrome_exe, '\\')
            ms = version_info['FileVersionMS']
            ls = version_info['FileVersionLS']
            version = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
            return version
        except Exception as e:
            print(f"Version detection error: {str(e)}")
            return None

    def setup_chrome_driver(self):
        try:
            chrome_path = self.channel_frame.chrome_path_edit.text().strip()
            
            # Add initial delay for stability
            time.sleep(2)
            
            chrome_version = self.get_chrome_version(chrome_path)
            if not chrome_version:
                raise Exception("Unable to detect Chrome version")
                
            options = webdriver.ChromeOptions()
            options.binary_location = chrome_path
            
            # Add additional stability options
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--remote-debugging-port=9222')
            options.add_argument('--start-maximized')
            options.page_load_strategy = 'normal'
            
            data_dir = os.path.join(os.path.dirname(chrome_path), 'Data')
            if os.path.exists(data_dir):
                options.add_argument(f'--user-data-dir={data_dir}')
            
            driver_path = ChromeDriverManager(driver_version=chrome_version).install()
            service = Service(executable_path=driver_path)
            service.creation_flags = CREATE_NO_WINDOW
            
            # Add retry mechanism
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.driver = webdriver.Chrome(service=service, options=options)
                    self.driver.set_window_size(1320, 960)
                    # Test driver by executing simple command
                    self.driver.execute_script('return document.readyState')
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise e
                    time.sleep(2)
                    
        except Exception as e:
            raise Exception(f"Failed to setup Chrome: {str(e)}")

    def download_chromedriver(self, chrome_version):
        try:
            # Create storage directory
            user_home = os.path.expanduser('~')
            chromedriver_dir = os.path.join(user_home, 'AppData', 'Local', 'ChromeDriver')
            os.makedirs(chromedriver_dir, exist_ok=True)
            
            # Extract major version from Chrome Portable
            major_version = chrome_version.split('.')[0]
            
            # Set driver version based on Chrome version
            driver_version_map = {
                "129": "129.0.6668.59",
                "128": "128.0.6462.59",
                # Add more versions as needed
            }
            
            driver_version = driver_version_map.get(major_version)
            if not driver_version:
                raise Exception(f"Unsupported Chrome version: {major_version}")
                
            # Download matching ChromeDriver
            driver_path = ChromeDriverManager(driver_version=driver_version).install()
            
            # Move to our managed location
            final_path = os.path.join(chromedriver_dir, f"chromedriver_{major_version}.exe")
            shutil.copy2(driver_path, final_path)
            
            return final_path
            
        except Exception as e:
            raise Exception(f"ChromeDriver download failed: {str(e)}")

    def find_existing_chromedriver(self, driver_dir, chrome_version):
        try:
            for root, dirs, files in os.walk(driver_dir):
                if 'chromedriver.exe' in files:
                    driver_path = os.path.join(root, 'chromedriver.exe')
                    # Verify driver version matches Chrome version
                    import subprocess
                    output = subprocess.check_output([driver_path, '--version']).decode()
                    if f"ChromeDriver {chrome_version}." in output:
                        return driver_path
            return None
        except:
            return None

    def process_next_edit_info(self):
        if not self.upload_queue:
            self.on_all_uploads_complete()
            return
            
        channel_frame = self.upload_queue[0]
        editor = EditVideoInfo(None, self.update_progress)
        
        try:
            # Initialize browser
            if channel_frame.firefox_radio.isChecked():
                profile_path = channel_frame.get_selected_profile()
                if not profile_path:
                    raise Exception("Chưa chọn profile Firefox")
                editor.setup_firefox_driver(profile_path)
            else:
                chrome_path = channel_frame.chrome_path_edit.text().strip()
                chrome_version = self.get_chrome_version(chrome_path)
                if not chrome_version:
                    raise Exception("Unable to detect Chrome version")
                editor.setup_chrome_driver(chrome_path, chrome_version)
                
            # Start edit process
            results = editor.start_edit_process()
            
            # Process results
            for result in results:
                if result["status"] == "success":
                    video = result["video"]
                    editor.update_video_info(
                        video,
                        channel_frame.title_edit.toPlainText(),
                        channel_frame.desc_edit.toPlainText(),
                        channel_frame.tags_edit.toPlainText(),
                        channel_frame.thumb_path_edit.text()
                    )
                    
            self.upload_queue.pop(0)
            self.process_next_edit_info()
            
        except Exception as e:
            self.on_upload_error(str(e))
        finally:
            if hasattr(editor, 'driver'):
                editor.driver.quit()

    def show_input_dialog(self, title, message):
        dialog = QInputDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLabelText(message)
        dialog.resize(500, 200)
        
        if dialog.exec_() == QDialog.Accepted:
            self.current_worker.input_text = dialog.textValue()
            self.current_worker.input_received.emit(dialog.textValue())
        else:
            self.current_worker.input_text = None
            self.current_worker.input_received.emit("")

    def show_confirmation_dialog(self, title, message):
        reply = QMessageBox.question(self, title, message,
                                   QMessageBox.Yes | QMessageBox.No)
        result = reply == QMessageBox.Yes
        self.current_worker.confirmation_result = result
        self.current_worker.confirmation_received.emit(result)

    def process_next_anti_bq(self):
        if self.anti_bq_queue:
            channel_frame = self.anti_bq_queue[0]
            # Initialize the current_worker first
            self.current_worker = AntiBQWorker(channel_frame, channel_frame.anti_bq_manager)
                
            # Connect all signals after worker is initialized
            self.current_worker.progress_updated.connect(self.update_progress)
            self.current_worker.process_complete.connect(self.on_anti_bq_channel_complete)
            self.current_worker.error_occurred.connect(self.on_anti_bq_error)
            self.current_worker.request_input.connect(self.show_input_dialog)
            self.current_worker.request_confirmation.connect(self.show_confirmation_dialog)
                
            # Start the worker
            self.current_worker.start()
            
            self.status_label.setText(f"Đang xử lý kháng BQ {channel_frame.findChild(QLabel).text()}")
        else:
            self.on_all_anti_bq_complete()
   
    def on_anti_bq_complete(self):
        # Remove completed channel from queue
        if self.anti_bq_queue:
            self.anti_bq_queue.pop(0)
            
        # Process next channel after delay
        QTimer.singleShot(2000, self.process_next_anti_bq)

    def process_next_anti_bq_channel(self):
        if self.anti_bq_queue:
            current_channel = self.anti_bq_queue[0]
            self.current_worker = AntiBQWorker(current_channel, current_channel.anti_bq_manager)
            
            # Connect signals including dialog handlers
            self.current_worker.progress_updated.connect(self.update_progress)
            self.current_worker.process_complete.connect(self.on_anti_bq_channel_complete)
            self.current_worker.error_occurred.connect(self.on_anti_bq_error)
            self.current_worker.request_input.connect(self.show_input_dialog)
            self.current_worker.request_confirmation.connect(self.show_confirmation_dialog)
            
            self.current_worker.start()

            channel_frame = self.anti_bq_queue[0]
            
            # Kiểm tra và đóng Firefox trước khi bắt đầu
            if channel_frame.anti_bq_firefox_radio.isChecked():
                channel_frame.close_existing_firefox()
            
            # Create worker with just the channel_frame
            self.status_label.setText(f"Đang xử lý kháng BQ {channel_frame.findChild(QLabel).text()}")
        else:
            self.on_all_anti_bq_complete()

    def on_anti_bq_channel_complete(self):
        if self.anti_bq_queue:
            self.anti_bq_queue.pop(0)  # Xóa kênh đã xử lý
        self.process_next_anti_bq_channel()

    def on_all_anti_bq_complete(self):
        QMessageBox.information(self, "Success", "Tất cả các kênh đã kháng BQ xong!")
        self.progress_bar.setValue(100)
        self.status_label.setText("Hoàn tất kháng BQ tất cả")

    def on_anti_bq_error(self, error_message):
        QMessageBox.warning(self, "Error", f"Kháng BQ thất bại: {error_message}")

    def add_channel(self):
        channel_frame = ChannelFrame(f"Kênh {len(self.channel_frames) + 1}")
        self.channels_layout.addWidget(channel_frame)
        self.channel_frames.append(channel_frame)
        
        # Kết nối signal mới
        channel_frame.action_type_changed.connect(self.update_action_button_text)
        
        # Load profiles ngay khi thêm kênh mới
        self.load_firefox_profiles(channel_frame)

    def load_firefox_profiles(self, specific_channel=None):
        try:
            firefox_path = os.path.expanduser('~\\AppData\\Roaming\\Mozilla\\Firefox')
            profiles_ini_path = os.path.join(firefox_path, 'profiles.ini')
            
            if os.path.exists(profiles_ini_path):
                profiles_dict = {}
                with open(profiles_ini_path, 'r', encoding='utf-8') as f:
                    current_section = None
                    current_data = {}
                    
                    for line in f:
                        line = line.strip()
                        if line.startswith('['):
                            if current_section and 'Name' in current_data and 'Path' in current_data:
                                profiles_dict[current_data['Name']] = current_data['Path'].split('/')[-1]
                            current_section = line[1:-1]
                            current_data = {}
                        elif '=' in line:
                            key, value = line.split('=', 1)
                            current_data[key.strip()] = value.strip()
                
                # Update profiles for specific channel or all channels
                channels_to_update = [specific_channel] if specific_channel else self.channel_frames
                for channel in channels_to_update:
                    channel.profiles_dict = profiles_dict.copy()
                    channel.profile_combo.clear()
                    channel.anti_bq_profile_combo.clear()  # Update both combos
                    channel.profile_combo.addItems(profiles_dict.keys())
                    channel.anti_bq_profile_combo.addItems(profiles_dict.keys())
                    
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Error loading Firefox profiles: {str(e)}")

    def update_action_button_text(self):
        # Get the sender channel frame
        sender = self.sender()
        if sender:
            self.current_channel_frame = sender
            
        if self.current_channel_frame:
            if self.current_channel_frame.upload_action.isChecked():
                self.upload_all_btn.setText("Upload Tất Cả")
            elif self.current_channel_frame.edit_info_action.isChecked():
                self.upload_all_btn.setText("Sửa Thông Tin Tất Cả")
            elif self.current_channel_frame.edit_status_action.isChecked():
                self.upload_all_btn.setText("Sửa Trạng Thái Tất Cả")

    def start_upload_all(self):
        # Get the active channel frame
        for frame in self.channel_frames:
            if frame.isActiveWindow():
                self.current_channel_frame = frame
                break
        
        # Clear existing queue
        self.upload_queue = []
        
        # Add all channels to queue
        for channel_frame in self.channel_frames:
            if channel_frame.isEnabled():  # Using correct Qt method name
                self.upload_queue.append(channel_frame)
        
        if not self.upload_queue:
            self.status_label.setText("Không có kênh nào được chọn")
            return
            
        # Check which action is selected
        if self.current_channel_frame and self.current_channel_frame.upload_action.isChecked():
            # Start upload process
            self.process_next_upload()
        elif self.current_channel_frame and self.current_channel_frame.edit_info_action.isChecked():
            # Start edit info process  
            self.process_next_edit_info()
        elif self.current_channel_frame and self.current_channel_frame.edit_status_action.isChecked():
            # Start edit status process
            self.process_next_edit_status()

    def process_next_upload(self):
        if self.upload_queue:
            # Clear previous worker
            if hasattr(self, 'current_worker') and self.current_worker:
                self.current_worker.cleanup_driver()
                self.current_worker = None
                
            channel_frame = self.upload_queue[0]
            self.current_worker = UploadWorker(channel_frame)
            
            # Connect signals
            self.current_worker.progress_updated.connect(self.update_progress)
            self.current_worker.upload_complete.connect(self.on_channel_complete)
            self.current_worker.error_occurred.connect(self.handle_upload_error)
            
            self.status_label.setText(f"Đang xử lý {channel_frame.findChild(QLabel).text()}")
            self.current_worker.start()

    def on_channel_complete(self):
        # Remove completed channel from queue
        if self.upload_queue:
            self.upload_queue.pop(0)
        
        # Cleanup current worker
        if self.current_worker:
            self.current_worker.cleanup_driver()
            self.current_worker = None
        
        # Process next channel after a short delay
        QTimer.singleShot(2000, self.process_next_upload)

    def handle_upload_error(self, error):
        if error == "LOGIN_FAILED":
            # Get current channel name for logging
            current_channel = self.upload_queue[0].findChild(QLabel).text()
            self.status_label.setText(f"Đăng nhập thất bại: {current_channel}")
            
            # Remove failed channel from queue
            self.upload_queue.pop(0)
            
            # Process next channel if available
            if self.upload_queue:
                self.process_next_upload()
            else:
                self.on_all_uploads_complete()
        else:
            # Handle other errors through existing error handler
            self.on_upload_error(error)

    def process_next_edit_info(self):
        if not self.upload_queue:
            self.on_all_uploads_complete()
            return
            
        channel_frame = self.upload_queue[0]
        
        try:
            # Initialize browser first
            if channel_frame.firefox_radio.isChecked():
                profile_path = channel_frame.get_selected_profile()
                if not profile_path:
                    raise Exception("Chưa chọn profile Firefox")
                    
                # Setup Firefox driver
                firefox_options = webdriver.FirefoxOptions()
                firefox_options.binary_location = r"C:/Program Files/Mozilla Firefox/firefox.exe"
                firefox_options.add_argument("-profile")
                firefox_options.add_argument(os.fspath(profile_path))
                
                driver = webdriver.Firefox(options=firefox_options)
                driver.set_window_size(1320, 960)
                
            else:
                # Setup Chrome Portable
                chrome_path = channel_frame.chrome_path_edit.text().strip()
                chrome_version = self.get_chrome_version(chrome_path)
                if not chrome_version:
                    raise Exception("Unable to detect Chrome version")
                    
                options = webdriver.ChromeOptions()
                options.binary_location = chrome_path
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--disable-gpu')
                options.add_argument('--remote-debugging-port=9222')
                
                data_dir = os.path.join(os.path.dirname(chrome_path), 'Data')
                if os.path.exists(data_dir):
                    options.add_argument(f'--user-data-dir={data_dir}')
                
                driver_path = ChromeDriverManager(driver_version=chrome_version).install()
                service = Service(executable_path=driver_path)
                service.creation_flags = CREATE_NO_WINDOW
                
                driver = webdriver.Chrome(service=service, options=options)
                driver.set_window_size(1320, 960)
                
            # Create editor with initialized driver
            editor = EditVideoInfo(driver, self.progress_updated)  # Use self.progress_updated instead
                
            # Start edit process
            results = editor.start_edit_process()
            
            # Process results
            for result in results:
                if result["status"] == "success":
                    video = result["video"]
                    editor.update_video_info(
                        video,
                        channel_frame.title_edit.toPlainText(),
                        channel_frame.desc_edit.toPlainText(),
                        channel_frame.tags_edit.toPlainText(),
                        channel_frame.thumb_path_edit.text()
                    )
                    
            self.upload_queue.pop(0)
            self.process_next_edit_info()
            
        except Exception as e:
            self.on_upload_error(str(e))
        finally:
            if 'driver' in locals():
                driver.quit()

    def on_all_uploads_complete(self):
        QMessageBox.information(self, "Success", "Tất cả các kênh đã upload xong!")
        self.progress_bar.setValue(100)
        self.status_label.setText("Hoàn tất tất cả")

    def update_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.status_label.setText(message)

    def on_upload_complete(self):
        QMessageBox.information(self, "Success", "Upload completed successfully!")
        self.progress_bar.setValue(100)
        self.status_label.setText("Upload completed")

    def on_upload_error(self, error_message):
        QMessageBox.warning(self, "Error", f"Upload failed: {error_message}")

class EditVideoInfo:
    def __init__(self, driver, progress_callback=None):
        self.driver = driver
        self.wait = WebDriverWait(self.driver, 20)
        self.progress_updated = progress_callback
        
    def setup_firefox_driver(self, profile_path):
        firefox_options = webdriver.FirefoxOptions()
        firefox_options.binary_location = r"C:/Program Files/Mozilla Firefox/firefox.exe"
        firefox_options.add_argument("-profile")
        firefox_options.add_argument(os.fspath(profile_path))
        
        self.driver = webdriver.Firefox(options=firefox_options)
        self.driver.set_window_size(1320, 960)
        
    def setup_chrome_driver(self):
        try:
            chrome_path = self.channel_frame.chrome_path_edit.text().strip()
            
            # Add initial delay for stability
            time.sleep(2)
            
            chrome_version = self.get_chrome_version(chrome_path)
            if not chrome_version:
                raise Exception("Unable to detect Chrome version")
                
            options = webdriver.ChromeOptions()
            options.binary_location = chrome_path
            
            # Add additional stability options
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--remote-debugging-port=9222')
            options.add_argument('--start-maximized')
            options.page_load_strategy = 'normal'
            
            data_dir = os.path.join(os.path.dirname(chrome_path), 'Data')
            if os.path.exists(data_dir):
                options.add_argument(f'--user-data-dir={data_dir}')
            
            driver_path = ChromeDriverManager(driver_version=chrome_version).install()
            service = Service(executable_path=driver_path)
            service.creation_flags = CREATE_NO_WINDOW
            
            # Add retry mechanism
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.driver = webdriver.Chrome(service=service, options=options)
                    self.driver.set_window_size(1320, 960)
                    # Test driver by executing simple command
                    self.driver.execute_script('return document.readyState')
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise e
                    time.sleep(2)
                    
        except Exception as e:
            raise Exception(f"Failed to setup Chrome: {str(e)}")

    def start_edit_process(self):
        try:
            self._navigate_to_content()
            self._check_login()
            self._access_content_tab()
            self._access_uploads_tab()
            video_list = self._get_video_list()
            return self._process_videos(video_list)
        except Exception as e:
            raise Exception(f"Lỗi trong quá trình sửa video: {str(e)}")

    def _navigate_to_content(self):
        print("Đang truy cập YouTube Studio...")
        self.driver.get(YTS.STUDIO_URL)
        if self.progress_updated:
            self.progress_updated.emit(10, "Đang truy cập trang Content")

    def _check_login(self):
        print("Kiểm tra trạng thái đăng nhập...")
        self.wait.until(EC.visibility_of_element_located((By.XPATH, YTS.AVATAR_BTN)))
        if self.progress_updated:
            self.progress_updated.emit(20, "Đang kiểm tra login")

    def _access_content_tab(self):
        print("Truy cập tab Content...")
        try:
            content_tab = self.wait.until(EC.visibility_of_element_located((By.XPATH, YTS.CONTENT_TAB)))
            content_tab.click()
            if self.progress_updated:
                self.progress_updated.emit(30, "Đang vào trang content")
        except Exception as e:
            print(f"Lỗi truy cập Content tab: {str(e)}")

    def _access_uploads_tab(self):
        print("Truy cập tab Uploads...")
        try:
            uploads_tab = self.wait.until(EC.visibility_of_element_located((By.XPATH, YTS.UPLOADS_TAB)))
            uploads_tab.click()
            if self.progress_updated:
                self.progress_updated.emit(40, "Đang tải danh sách video")
        except Exception as e:
            raise Exception(f"Không thể truy cập tab Uploads: {str(e)}")

    def _get_video_list(self):
        print("Đang lấy danh sách video...")
        video_container = self.wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "ytcp-video-section-content#video-list"))
        )
        return video_container.find_elements(By.CSS_SELECTOR, "ytcp-video-row.style-scope.ytcp-video-section-content")

    def _process_videos(self, video_list):
        results = []
        if not video_list:
            raise Exception("Không tìm thấy video nào trong danh sách")
            
        print(f"Tìm thấy {len(video_list)} video")
        
        for index, video in enumerate(video_list):
            try:
                # Wait for video row to be fully loaded
                self.wait.until(EC.presence_of_element_located((
                    By.CSS_SELECTOR, 
                    "ytcp-video-row.style-scope.ytcp-video-section-content"
                )))
                
                # Find and click the menu button first
                menu_button = video.find_element(
                    By.CSS_SELECTOR,
                    "ytcp-button[aria-label='Tùy chọn']"
                )
                menu_button.click()
                
                # Wait for edit button in dropdown menu
                edit_button = self.wait.until(
                    EC.element_to_be_clickable((
                        By.CSS_SELECTOR,
                        "tp-yt-paper-item[test-id='EDIT']"
                    ))
                )
                edit_button.click()
                
                # Handle the edit popup
                popup_elements = self._handle_edit_popup()
                
                if self.progress_updated:
                    progress = 40 + (50 * (index + 1) // len(video_list))
                    self.progress_updated.emit(progress, f"Đang xử lý video {index + 1}/{len(video_list)}")
                
                results.append({"status": "success", "video": video})
                
            except Exception as e:
                print(f"Lỗi xử lý video {index + 1}: {str(e)}")
                results.append({"status": "error", "video": video, "error": str(e)})
        
        return results


    def _handle_edit_popup(self):
        # Xử lý tiêu đề
        title_input = self.wait.until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR, 
                "#container-content.style-scope.ytcp-social-suggestions-textbox"
            ))
        )

        # Xử lý mô tả
        desc_input = self.wait.until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                "#container-content.style-scope.ytcp-social-suggestions-textbox:nth-child(2)"
            ))
        )

        # Xử lý thumbnail
        thumbnail_uploader = self.wait.until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                "ytcp-thumbnail-uploader[image-size='IMAGE_2MB']"
            ))
        )

        # Xử lý tags
        toggle_button = self.wait.until(
            EC.element_to_be_clickable((
                By.CSS_SELECTOR,
                "ytcp-button#toggle-button"
            ))
        )
        toggle_button.click()

        tags_container = self.wait.until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR,
                "ytcp-form-input-container#tags-container"
            ))
        )

        return {
            "title_input": title_input,
            "desc_input": desc_input,
            "thumbnail_uploader": thumbnail_uploader,
            "tags_container": tags_container
        }

    def update_video_info(self, video_element, new_title, new_desc, new_tags, thumbnail_path=None):
        try:
            # Get popup elements
            popup_elements = self._handle_edit_popup()
            
            # Update title
            title_input = popup_elements["title_input"]
            title_input.clear()
            title_input.send_keys(new_title)
            
            # Update description
            desc_input = popup_elements["desc_input"]
            desc_input.clear()
            desc_input.send_keys(new_desc)
            
            # Update tags
            tags_container = popup_elements["tags_container"]
            tags_container.clear()
            tags_container.send_keys(new_tags)
            
            # Update thumbnail if provided
            if thumbnail_path:
                thumbnail_uploader = popup_elements["thumbnail_uploader"]
                thumbnail_input = thumbnail_uploader.find_element(By.CSS_SELECTOR, "input[type='file']")
                thumbnail_input.send_keys(thumbnail_path)
                
            # Save changes
            save_button = self.wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "ytcp-button#save-button"))
            )
            save_button.click()
            
            # Wait for save completion
            self.wait.until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, "ytcp-uploads-dialog"))
            )
            
            if self.progress_updated:
                self.progress_updated.emit(90, "Đã lưu thay đổi")
                
        except Exception as e:
            raise Exception(f"Lỗi khi cập nhật thông tin video: {str(e)}")

class EditVideoStatus:
    def __init__(self, driver, progress_callback=None):
        self.driver = driver
        self.wait = WebDriverWait(self.driver, 20)
        self.progress_updated = progress_callback

    def start_edit_process(self):
        try:
            self._navigate_to_content()
            self._check_login()
            self._access_content_tab()
            self._access_uploads_tab()
            video_list = self._get_video_list()
            return self._process_videos(video_list)
        except Exception as e:
            raise Exception(f"Lỗi trong quá trình sửa trạng thái: {str(e)}")

    # Các phương thức navigation giống EditVideoInfo
    
    def _process_videos(self, video_list):
        results = []
        for video in video_list:
            try:
                # Tìm và click vào menu visibility
                visibility_button = video.find_element(
                    By.CSS_SELECTOR, 
                    "ytcp-video-visibility-select"
                )
                visibility_button.click()
                
                # Xử lý popup visibility
                self._handle_visibility_popup()
                
                results.append({"status": "success", "video": video})
            except Exception as e:
                results.append({"status": "error", "video": video, "error": str(e)})
        
        return results

    def _handle_visibility_popup(self):
        # Xử lý popup visibility
        visibility_dialog = self.wait.until(
            EC.presence_of_element_located((
                By.CSS_SELECTOR, 
                "ytcp-video-visibility-dialog"
            ))
        )
        
        # Các elements trong popup
        schedule_radio = visibility_dialog.find_element(By.CSS_SELECTOR, "#schedule-radio-button")
        public_radio = visibility_dialog.find_element(By.CSS_SELECTOR, "#public-radio-button")
        
        date_picker = visibility_dialog.find_element(By.CSS_SELECTOR, "#datepicker-trigger")
        time_input = visibility_dialog.find_element(By.CSS_SELECTOR, "#time-of-day-input")
        
        return {
            "schedule_radio": schedule_radio,
            "public_radio": public_radio,
            "date_picker": date_picker,
            "time_input": time_input
        }

class DragDropListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            for url in urls:
                file_path = url.toLocalFile()
                if file_path.lower().endswith(('.mp4', '.avi', '.mkv')):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        files = [url.toLocalFile() for url in event.mimeData().urls()]
        self.parent().add_files_to_list(files)
        event.acceptProposedAction()

class AntiBQManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quản lý nội dung kháng BQ")
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)
        self.init_ui()
        self.load_saved_content()

    def init_ui(self):
        layout = QVBoxLayout()

        # Input section
        input_group = QGroupBox("Nhập nội dung mới")
        input_layout = QVBoxLayout()

        # Title input
        title_layout = QHBoxLayout()
        title_layout.addWidget(QLabel("Tiêu đề video:"))
        self.title_edit = QLineEdit()
        title_layout.addWidget(self.title_edit)

        # Content input
        content_layout = QVBoxLayout()
        content_layout.addWidget(QLabel("Nội dung kháng:"))
        self.content_edit = QTextEdit()
        content_layout.addWidget(self.content_edit)

        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Lưu")
        clear_btn = QPushButton("Xóa trắng")
        save_btn.clicked.connect(self.save_content)
        clear_btn.clicked.connect(self.clear_fields)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(clear_btn)

        input_layout.addLayout(title_layout)
        input_layout.addLayout(content_layout)
        input_layout.addLayout(btn_layout)
        input_group.setLayout(input_layout)

        # Saved content list
        list_group = QGroupBox("Danh sách nội dung đã lưu")
        list_layout = QVBoxLayout()
        self.content_list = QListWidget()
        self.content_list.itemClicked.connect(self.load_content)
        
        # Delete and edit buttons
        control_layout = QHBoxLayout()
        edit_btn = QPushButton("Sửa")
        delete_btn = QPushButton("Xóa")
        edit_btn.clicked.connect(self.edit_content)
        delete_btn.clicked.connect(self.delete_selected)
        control_layout.addWidget(edit_btn)
        control_layout.addWidget(delete_btn)

        list_layout.addWidget(self.content_list)
        list_layout.addLayout(control_layout)
        list_group.setLayout(list_layout)

        # Add all components
        layout.addWidget(input_group)
        layout.addWidget(list_group)
        self.setLayout(layout)

    def save_content(self):
        title = self.title_edit.text().strip()
        content = self.content_edit.toPlainText().strip()
        
        if not title or not content:
            QMessageBox.warning(self, "Lỗi", "Vui lòng nhập đầy đủ tiêu đề và nội dung!")
            return

        data = self.load_data()
        data[title] = content
        self.save_data(data)
        self.update_content_list()
        self.clear_fields()
        QMessageBox.information(self, "Thành công", "Đã lưu nội dung!")

    def edit_content(self):
        current_item = self.content_list.currentItem()
        if current_item:
            title = current_item.text()
            data = self.load_data()
            if title in data:
                self.title_edit.setText(title)
                self.content_edit.setText(data[title])

    def delete_selected(self):
        current_item = self.content_list.currentItem()
        if current_item:
            reply = QMessageBox.question(self, 'Xác nhận', 
                                       'Bạn có chắc muốn xóa nội dung này?',
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                title = current_item.text()
                data = self.load_data()
                if title in data:
                    del data[title]
                    self.save_data(data)
                    self.update_content_list()
                    self.clear_fields()

    def load_data(self):
        try:
            with open('anti_bq_content.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def get_content_for_title(self, video_title):
        data = self.load_data()
        # Tìm nội dung phù hợp nhất dựa trên tiêu đề video
        for saved_title, content in data.items():
            if video_title.lower().find(saved_title.lower()) != -1:
                return content
        return None

    def save_data(self, data):
        with open('anti_bq_content.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def update_content_list(self):
        self.content_list.clear()
        data = self.load_data()
        self.content_list.addItems(sorted(data.keys()))

    def clear_fields(self):
        self.title_edit.clear()
        self.content_edit.clear()

    def load_content(self, item):
        title = item.text()
        data = self.load_data()
        if title in data:
            self.title_edit.setText(title)
            self.content_edit.setText(data[title])

    def load_saved_content(self):
        """Load and display previously saved content in the list"""
        try:
            data = self.load_data()
            self.content_list.clear()
            self.content_list.addItems(sorted(data.keys()))
        except Exception as e:
            QMessageBox.warning(self, "Lỗi", f"Không thể tải nội dung đã lưu: {str(e)}")

class AntiBQWorker(QThread):
    progress_updated = pyqtSignal(int, str)
    process_complete = pyqtSignal()
    error_occurred = pyqtSignal(str)
    request_input = pyqtSignal(str, str)
    request_confirmation = pyqtSignal(str, str)
    input_received = pyqtSignal(str)
    confirmation_received = pyqtSignal(bool)
    show_continue_dialog = pyqtSignal(str)

    def __init__(self, channel_frame, manager):
        super().__init__()
        self.channel_frame = channel_frame
        self.manager = manager
        self.driver = None
        self.is_browser_hidden = False
        self.input_text = None
        self.confirmation_result = None
        show_continue_dialog = pyqtSignal(str, name='showContinueDialog')

    def close_webdriver_processes(self):
        try:
                for process in psutil.process_iter(['pid', 'name']):
                    # Only target chromedriver.exe and geckodriver.exe
                    if process.info['name'] in ['chromedriver.exe', 'geckodriver.exe']:
                        psutil.Process(process.info['pid']).terminate()
                time.sleep(2)
        except Exception as e:
            print(f"Error closing WebDriver processes: {e}")

    def setup_firefox_driver(self):
        selected_profile = self.channel_frame.anti_bq_profile_combo.currentText()
        profile_id = self.channel_frame.profiles_dict[selected_profile]
        profile_path = os.path.expanduser(f'~\\AppData\\Roaming\\Mozilla\\Firefox\\Profiles\\{profile_id}')
        
        firefox_options = webdriver.FirefoxOptions()
        firefox_options.binary_location = r"C:/Program Files/Mozilla Firefox/firefox.exe"
        firefox_options.add_argument("-profile")
        firefox_options.add_argument(os.fspath(profile_path))
        
        self.driver = webdriver.Firefox(options=firefox_options)
        self.driver.set_window_size(1320, 960)

    def get_chrome_version(self, chrome_path):
        try:
            chrome_dir = os.path.dirname(chrome_path)
            chrome_exe = os.path.join(chrome_dir, 'App', 'Chrome-bin', 'chrome.exe')
            version_info = win32api.GetFileVersionInfo(chrome_exe, '\\')
            ms = version_info['FileVersionMS']
            ls = version_info['FileVersionLS']
            version = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
            return version
        except Exception as e:
            print(f"Version detection error: {str(e)}")
            return None

    def setup_chrome_driver(self):
        try:
            chrome_path = self.channel_frame.anti_bq_chrome_path_edit.text().strip()
            
            # Get Chrome version automatically
            chrome_version = self.get_chrome_version(chrome_path)
            if not chrome_version:
                raise Exception("Unable to detect Chrome version")
                
            print(f"Detected Chrome version: {chrome_version}")
            
            options = webdriver.ChromeOptions()
            options.binary_location = chrome_path
            
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--remote-debugging-port=9222')
            
            data_dir = os.path.join(os.path.dirname(chrome_path), 'Data')
            if os.path.exists(data_dir):
                options.add_argument(f'--user-data-dir={data_dir}')
            
            # Use detected version for ChromeDriver
            driver_path = ChromeDriverManager(driver_version=chrome_version).install()
            service = Service(executable_path=driver_path)
            service.creation_flags = CREATE_NO_WINDOW
            
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.set_window_size(1320, 960)
            
            print("Chrome driver setup successful")
            
        except Exception as e:
            print(f"Chrome setup error: {str(e)}")
            raise Exception(f"Failed to setup Chrome: {str(e)}")

    def download_chromedriver(self, chrome_version):
        try:
            # Create storage directory
            user_home = os.path.expanduser('~')
            chromedriver_dir = os.path.join(user_home, 'AppData', 'Local', 'ChromeDriver')
            os.makedirs(chromedriver_dir, exist_ok=True)
            
            # Extract major version from Chrome Portable
            major_version = chrome_version.split('.')[0]
            
            # Set driver version based on Chrome version
            driver_version_map = {
                "129": "129.0.6668.59",
                "128": "128.0.6462.59",
                # Add more versions as needed
            }
            
            driver_version = driver_version_map.get(major_version)
            if not driver_version:
                raise Exception(f"Unsupported Chrome version: {major_version}")
                
            # Download matching ChromeDriver
            from webdriver_manager.chrome import ChromeDriverManager
            driver_path = ChromeDriverManager(driver_version=driver_version).install()
            
            # Move to our managed location
            final_path = os.path.join(chromedriver_dir, f"chromedriver_{major_version}.exe")
            import shutil
            shutil.copy2(driver_path, final_path)
            
            return final_path
            
        except Exception as e:
            raise Exception(f"ChromeDriver download failed: {str(e)}")

    def find_existing_chromedriver(self, driver_dir, chrome_version):
        try:
            for root, dirs, files in os.walk(driver_dir):
                if 'chromedriver.exe' in files:
                    driver_path = os.path.join(root, 'chromedriver.exe')
                    # Verify driver version matches Chrome version
                    import subprocess
                    output = subprocess.check_output([driver_path, '--version']).decode()
                    if f"ChromeDriver {chrome_version}." in output:
                        return driver_path
            return None
        except:
            return None
   
    # Modify get_dispute_text method
    def get_dispute_text(self, claim_title):
        data = self.manager.load_data()
        
        for saved_title, content in data.items():
            if saved_title.lower() in claim_title.lower():
                return content
                
        # Emit signals and wait for response
        self.request_confirmation.emit(
            "Nội dung kháng cáo không tìm thấy",
            f"Không tìm thấy nội dung kháng cáo cho video '{claim_title}'.\nBạn có muốn thêm nội dung mới không?"
        )
        
        # Use event loop to wait for response
        loop = QEventLoop()
        self.confirmation_received.connect(loop.quit)
        loop.exec_()
        
        if self.confirmation_result:
            self.request_input.emit(
                "Nhập nội dung kháng cáo",
                f"Nhập nội dung kháng cáo cho video '{claim_title}':"
            )
            
            # Wait for input
            loop = QEventLoop()
            self.input_received.connect(loop.quit)
            loop.exec_()
            
            if self.input_text:
                data[claim_title] = self.input_text
                self.manager.save_data(data)
                return self.input_text
                
        return None

    def match_claim_title(self, claim_title):
        # Load saved content data
        data = self.manager.load_data()
        
        # Try to find matching title
        for saved_title in data.keys():
            if saved_title.lower() in claim_title.lower():
                return True
        return False

    def run(self):
        process_complete = pyqtSignal()  # Thêm signal này
        try:
            self.close_webdriver_processes()
            
            if self.channel_frame.anti_bq_firefox_radio.isChecked():
                print("Using Firefox for Anti-BQ")
                self.setup_firefox_driver()
            else:
                # Validate Chrome path before setup
                chrome_path = self.channel_frame.anti_bq_chrome_path_edit.text().strip()
                print(f"Chrome path for validation: {chrome_path}")
                
                if not chrome_path:
                    raise Exception("Chrome path is empty. Please select Chrome executable file")
                if not os.path.exists(chrome_path):
                    raise Exception(f"Chrome file not found at: {chrome_path}")
                if not chrome_path.lower().endswith('.exe'):
                    raise Exception("Selected file must be an executable (.exe) file")
                    
                print("Chrome path validated successfully")
                self.setup_chrome_driver()
                self.channel_frame.toggle_browser_btn.setEnabled(True)
            self.process_anti_bq()
            self.process_complete.emit()  # Emit signal khi hoàn thành
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            if self.driver:
                self.driver.quit()
            self.channel_frame.toggle_browser_btn.setEnabled(False)

    def process_anti_bq(self):
        wait = WebDriverWait(self.driver, 10)
        
        try:
            # 1. Navigate to content page
            print("Step 1: Navigating to YouTube Studio content page...")
            self.driver.get(YTS.STUDIO_URL)
            print(f"Current URL: {self.driver.current_url}")
            self.progress_updated.emit(10, "Đang truy cập trang Content")

            # 2. Wait for page load
            # Check login status by avatar button
            print("Checking login status...")
            avatar = wait.until(EC.visibility_of_element_located((By.XPATH, YTS.AVATAR_BTN)))
            print("Đang tìm thông tin đăng nhập")
            self.progress_updated.emit(20, "Đang kiểm tra login")

            # 3. Wait for and click Videos tab
            print("\nStep 3: Looking for Videos tab...")
            try:
                print("Looking for content tab...")
                content_tab = wait.until(EC.visibility_of_element_located((By.XPATH, YTS.CONTENT_TAB)))
                print("đã tìm thấy tabs content")
                content_tab.click()
                self.progress_updated.emit(30, "Đang vào trang content")
            except Exception as e:
                print(f"Videos tab interaction error: {str(e)}")
                print("Continuing as tab might be pre-selected...")

            # 4. Wait for and click Uploads tab
            print("\nStep 4: Video tabs...")
            try:
                print("Looking for videos container...")
                videos_container = wait.until(EC.visibility_of_element_located((By.XPATH, YTS.UPLOADS_TAB)))
                print("đã tìm thấy tab video")
                videos_container.click()
                self.progress_updated.emit(40, "Đang tiến hành kháng BQ")
            except Exception as e:
                print(f"Error accessing Uploads tab: {str(e)}")
                raise Exception(f"Không thể truy cập tab Uploads: {str(e)}")

            # 5. Process copyright claims
            print("\nStep 5: Processing copyright claims...")
            try:
                current_page = 1
                while True:
                    print(f"\nProcessing Page {current_page}")
                    # Find and process videos on current page
                    video_list = wait.until(EC.presence_of_element_located(
                        (By.CSS_SELECTOR, YTS.VIDEO_LIST)))
                    
                    video_rows = video_list.find_elements(
                        By.CSS_SELECTOR, YTS.VIDEO_ROW)
                    print(f"Found {len(video_rows)} videos to process")
                    
                    # Process each video row sequentially
                    for index, row in enumerate(video_rows):
                        print(f"Processing video {index + 1}/{len(video_rows)}")
                        
                        # Tìm restriction_elem trong phạm vi của row hiện tại
                        restriction_elem = row.find_element(By.ID, YTS.RESTRICTIONS_TEXT)
                        restriction_text = restriction_elem.text.strip()
                        print(f"Restriction text: {restriction_text}")
                        
                        if restriction_text in YTS.COPYRIGHT_TEXTS:
                            print("Copyright restriction found, processing...")
                            
                            self.driver.execute_script(
                                "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", 
                                restriction_elem)
                            time.sleep(2)
                            
                            restriction_elem.click()
                            time.sleep(1)
                            
                            see_details = wait.until(EC.visibility_of_element_located(
                                (By.XPATH, YTS.SEE_DETAIL_BUTTON)))
                            see_details.click()
                            print("Clicked See details button")
                        
                            self.process_copyright_claims()
                        
                        time.sleep(1)
                    
                    print(f"\nCompleted processing page {current_page}")
                    
                    # Check for next page and ask user
                    if self.has_next_page():
                        # Emit signal to show dialog in main thread
                        process_next = self.show_continue_dialog.emit(
                            f"Đã hoàn thành xử lý trang {current_page}. Bạn có muốn tiếp tục xử lý trang tiếp theo không?")
                        
                        if process_next:
                            current_page += 1
                            self.go_to_next_page()
                            time.sleep(2)
                            self.progress_updated.emit(70, f"Đang xử lý trang {current_page}")
                        else:
                            print("User chose to stop processing")
                            break
                    else:
                        print("No more pages available")
                        break
                
                self.progress_updated.emit(100, "Hoàn thành xử lý kháng BQ")
                self.process_complete.emit()
                
            except Exception as e:
                print(f"\nError during copyright claim processing: {str(e)}")
                raise Exception(f"Lỗi khi xử lý copyright claims: {str(e)}")
                
        except Exception as e:
            print(f"\nFatal error in process_anti_bq: {str(e)}")
            raise

    def process_copyright_claims(self):
        wait = WebDriverWait(self.driver, 10)
        
        try:
            while True:
                # Add explicit wait for claims container
                time.sleep(1)
                claims_container = wait.until(EC.presence_of_element_located((
                    By.CSS_SELECTOR, YTS.CLAIMS_CONTAINER)))
                
                claim_rows = wait.until(EC.presence_of_all_elements_located((
                    By.XPATH, YTS.CLAIM_ROW
                )))
                
                print(f"Found {len(claim_rows)} claim rows")
                
                unprocessed_found = False
                processed_count = 0
                total_claims = len(claim_rows)
                
                for row in claim_rows:
                    try:
                        dispute_status = row.find_elements(By.CSS_SELECTOR, YTS.DISPUTE_STATUS)
                        if dispute_status:
                            processed_count += 1
                            continue
                            
                        unprocessed_found = True
                        print(f"Processing claim {processed_count + 1}/{total_claims}")
                        
                        # Scroll row into view
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", row)
                        time.sleep(1)
                        
                        # Get asset title
                        asset_title = row.find_element(
                            By.CSS_SELECTOR, 
                            YTS.ASSET_TITLE
                        ).text
                        print(f"Processing claim: {asset_title}")
                        
                        # Click action button with retry
                        max_retries = 3
                        for attempt in range(max_retries):
                            try:
                                action_button = row.find_element(
                                    By.CSS_SELECTOR,
                                    YTS.ACTIONS_BUTTON
                                )
                                self.driver.execute_script("arguments[0].click();", action_button)
                                time.sleep(2)
                                break
                            except Exception as e:
                                if attempt == max_retries - 1:
                                    raise e
                                time.sleep(1)
                        
                        # Process the dispute with retry mechanism
                        retry_count = 0
                        while retry_count < 3:
                            try:
                                self.handle_dispute_popup(asset_title)
                                break
                            except Exception as e:
                                retry_count += 1
                                if retry_count == 3:
                                    raise e
                                print(f"Retrying dispute process attempt {retry_count}/3")
                                time.sleep(2)
                                
                        break  # Successfully processed one claim
                        
                    except Exception as e:
                        print(f"Error processing individual claim: {str(e)}")
                        # Try to recover by closing any open dialogs
                        try:
                            actions = ActionChains(self.driver)
                            actions.send_keys(Keys.ESCAPE).perform()
                            time.sleep(2)
                        except:
                            pass
                        continue
                
                if not unprocessed_found:
                    print("All claims in this video have been processed")
                    # Add retry mechanism for closing dialog
                    for _ in range(3):
                        try:
                            close_button = wait.until(EC.element_to_be_clickable((
                                By.CSS_SELECTOR, 
                                YTS.CLOSE_DIALOG
                            )))
                            close_button.click()
                            time.sleep(3)
                            break
                        except:
                            time.sleep(1)
                    break
                    
                time.sleep(2)
                
        except Exception as e:
            print(f"Error in process_copyright_claims: {str(e)}")
            raise Exception(f"Lỗi khi xử lý claim: {str(e)}")

    def handle_dispute_popup(self, asset_title):
        wait = WebDriverWait(self.driver, 10)
        
        try:
            # Click dispute option
            dispute_option = wait.until(EC.visibility_of_element_located((
                By.XPATH, 
                YTS.DISPUTE_OPTION
            )))
            dispute_option.click()
            print(" Select Option Dispute")
            time.sleep(1)

            # Click confirm 
            try:
                confirm_btn = wait.until(EC.visibility_of_element_located((
                    By.XPATH, YTS.CONFIRM_BUTTON
                )))
            except:
                confirm_btn = wait.until(EC.visibility_of_element_located((
                    By.XPATH, YTS.CONTINUE_BUTTON
                )))
            confirm_btn.click()
            print("Click button to next step")
            time.sleep(1)

            # Click continue Overview
            confirm_btn_Overview = wait.until(EC.visibility_of_element_located((
                By.XPATH,YTS.CONTINUE_BUTTON
            )))
            confirm_btn_Overview.click()
            print("Click button on Overview")
            time.sleep(1)

            #Radio button list select
            radio_btn_list = wait.until(EC.visibility_of_element_located((By.XPATH, YTS.RADIO_GROUP)))
            second_radio = radio_btn_list.find_element(By.XPATH, YTS.LICENSE_RADIO_BUTTON)
            second_radio.click()
            print("Select License radio button")
            time.sleep(1)  

            # Click continue Reason
            confirm_btn_Reason = wait.until(EC.visibility_of_element_located((
                By.XPATH, YTS.CONTINUE_BUTTON
            )))
            confirm_btn_Reason.click()
            print("Click button next in Reason")
            time.sleep(1)

            #Review check box tick
            review_checkbox = wait.until(EC.visibility_of_element_located((By.XPATH, YTS.REVIEW_CHECKBOX)))
            review_checkbox.click()
            print("click CheckBox accept")
            time.sleep(1)

            # Click continue Details
            continue_btn_Details = wait.until(EC.visibility_of_element_located((
                By.XPATH, YTS.CONTINUE_BUTTON
            )))
            continue_btn_Details.click()
            print("Click button Next in Details")
            time.sleep(1)

            dispute_text = self.get_dispute_text(asset_title)
            if not dispute_text:
                # Show dialog to get new content from user
                reply = QMessageBox.question(
                    None,
                    "Nội dung kháng cáo không tìm thấy",
                    f"Không tìm thấy nội dung kháng cáo cho video '{asset_title}'.\nBạn có muốn thêm nội dung mới không?",
                    QMessageBox.Yes | QMessageBox.No
                )
                
                if reply == QMessageBox.Yes:
                    dialog = QInputDialog()
                    dialog.setWindowTitle("Nhập nội dung kháng cáo")
                    dialog.setLabelText(f"Nhập nội dung kháng cáo cho video '{asset_title}':")
                    dialog.resize(500, 200)
                    
                    if dialog.exec_():
                        dispute_text = dialog.textValue()
                        # Save new content
                        data = self.manager.load_data()
                        data[asset_title] = dispute_text
                        self.manager.save_data(data)
                    else:
                        print(f"Skipping dispute - user cancelled input for: {asset_title}")
                        return
                else:
                    print(f"Skipping dispute - no content provided for: {asset_title}")
                    return

            # Continue with the dispute process
            textarea = wait.until(EC.visibility_of_element_located((
                By.XPATH, YTS.RATIONALE_TEXTAREA
            )))
            textarea.click()
            textarea.clear()
            textarea.send_keys(dispute_text)
            print("insert content coppyright to text area")
            
            # Find all checkboxes first
            checkboxes = wait.until(EC.presence_of_all_elements_located((
                By.XPATH, YTS.FORM_CHECKBOXES
            )))

            # Click each checkbox in order
            for i, checkbox in enumerate(checkboxes[:3]):  # Limit to first 3 checkboxes
                print(f"Clicking checkbox {i+1}")
                checkbox.click()
                time.sleep(1)

            # Fill signature
            signature = wait.until(EC.presence_of_element_located(
                (By.ID, YTS.SIGNATURE_FIELD)))
            signature.send_keys("Khanhtbk")
            print("Đã nhập signature")
            
            # Submit dispute
            submit_btn = wait.until(EC.element_to_be_clickable(
                (By.ID, YTS.SUBMIT_BUTTON)))
            submit_btn.click()
            print("Click button accept")
            print("Đang kiểm tra thông tin BQ khác...")
            
            max_retries = 3
            retry_count = 0

            while retry_count < max_retries:
                try:
                    close_Dispute_submitted = wait.until(EC.element_to_be_clickable((
                        By.XPATH, YTS.CLOSE_SUMBITIED_DISPUTE
                    )))
                    self.driver.execute_script("arguments[0].click();", close_Dispute_submitted)
                    time.sleep(3)
                    
                    # Kiểm tra nếu nút close đã biến mất
                    try:
                        wait.until_not(EC.presence_of_element_located((
                            By.XPATH, YTS.CLOSE_SUMBITIED_DISPUTE
                        )))
                        print("Close button successfully disappeared")
                        break
                    except TimeoutException:
                        retry_count += 1
                        if retry_count == max_retries:
                            # Thử phương án khác nếu không click được
                            actions = ActionChains(self.driver)
                            actions.send_keys(Keys.ESCAPE).perform()
                            time.sleep(1)
                except Exception:
                    break

        except Exception as e:
            raise Exception(f"Lỗi khi xử lý dispute popup: {str(e)}")

    def has_next_page(self):
        try:
            # Find the next page button
            next_button = self.driver.find_element(
                By.XPATH, 
                YTS.NEXT_PAGE_CONTINUE
            )
            
            # Check if button is enabled
            return 'disabled' not in next_button.get_attribute('class')
        except:
            return False

    def go_to_next_page(self):
        next_button = self.driver.find_element(
            By.XPATH, 
            YTS.NEXT_PAGE_CONTINUE
        )
        next_button.click()
        time.sleep(2)  # Wait for page load

    def show_continue_dialog(self, message):
        reply = QMessageBox.question(self, 'Tiếp tục?', message,
                                   QMessageBox.Yes | QMessageBox.No)
        return reply == QMessageBox.Yes

    def show_confirmation_dialog(self, title, message):
        reply = QMessageBox.question(self, title, message,
                                   QMessageBox.Yes | QMessageBox.No)
        return reply == QMessageBox.Yes