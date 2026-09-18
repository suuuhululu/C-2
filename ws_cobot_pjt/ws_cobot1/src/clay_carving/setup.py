from setuptools import find_packages, setup

package_name = 'clay_carving'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    package_data={package_name: ['designs/*.svg']},
    include_package_data=True,
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Lee Siyul',
    maintainer_email='sskywalker1209@gmail.com',
    description='지점토 조각: 스캔·그리퍼·송곳 길이·SVG 도안 그리기 노드 (C-2)',
    license='MIT',
    entry_points={
        'console_scripts': [
            # 1번: 지점토 위치·크기 (v1 납작한 지점토 / v2 높이·부피까지)
            'clay_scan = clay_carving.clay_scan:main',
            'clay_scan2 = clay_carving.clay_scan2:main',
            # 2번: 그리퍼 y/n
            'gripper_ui = clay_carving.gripper_ui:main',
            # 3번: 송곳 접촉·길이
            'force_probe = clay_carving.force_probe:main',
            # 4번: SVG 도안 그리기 (clay_draw <svg>), clay_heart 는 같은 프로그램의 옛 이름
            'clay_draw = clay_carving.clay_heart:main',
            'clay_heart = clay_carving.clay_heart:main',
            # 시작 신호
            'clay_start = clay_carving.clay_start:main',
        ],
    },
)
