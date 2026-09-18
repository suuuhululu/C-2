from setuptools import find_packages, setup

package_name = 'clay_hmi'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        # Qt Designer 화면 파일: 수업 예제처럼 share/<pkg>/ 에 설치하고 get_package_share_directory 로 찾는다
        ('share/' + package_name, ['clay_hmi/clay_hmi.ui']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Lee Siyul',
    maintainer_email='sskywalker1209@gmail.com',
    description='지점토 조각 관리자 HMI (PyQt5, C-2)',
    license='MIT',
    entry_points={
        'console_scripts': [
            'hmi_main = clay_hmi.hmi_main:main',
        ],
    },
)
