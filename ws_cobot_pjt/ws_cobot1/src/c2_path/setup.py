from setuptools import setup, find_packages

package_name = "c2_path"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="C-2 team",
    maintainer_email="167942097+suuuhululu@users.noreply.github.com",
    description=(
        "C-2 좌표 생성 패키지. 이미지·SVG -> 2D 추출·최적화 -> 원통 표면 매핑 -> "
        "실행 경로(GeneratePath v2). 로봇을 실행하지 않는다."
    ),
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "path_planner_node = c2_path.node:main",
        ],
    },
)
