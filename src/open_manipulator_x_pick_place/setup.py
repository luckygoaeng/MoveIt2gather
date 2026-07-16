from setuptools import find_packages
from setuptools import setup

package_name = 'open_manipulator_x_pick_place'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=[]),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='DGIST CSI Lab',
    maintainer_email='yhy030721@gmail.com',
    description='Fixed-pose pick-and-place script for OpenManipulator-X using moveit_py',
    license='Apache License 2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'pick_and_place = open_manipulator_x_pick_place.pick_and_place:main',
            'calibrate_camera_to_base = open_manipulator_x_pick_place.calibrate_camera_to_base:main',
            'pick_and_place_aruco = open_manipulator_x_pick_place.pick_and_place_aruco:main',
        ],
    },
)
