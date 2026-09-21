from setuptools import setup


package_name = "c2_process"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="C-2 team",
    maintainer_email="167942097+suuuhululu@users.noreply.github.com",
    description="C-2 fixed-drill process controller",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "process_controller_node = c2_process.node:main",
            "real_preparation_node = c2_process.node:real_preparation_main",
        ],
    },
)
