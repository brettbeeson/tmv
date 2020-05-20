import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

    extras = {
        'advanced': ['ascii_graph']
    }

setuptools.setup(
    name="timemv",
    version="0.0.1",
    author="Brett Beeson",
    author_email="brettbeeson@fastmail.com",
    include_package_data=True,
    description="Time Made Visible - a timelapse system",
    long_description="A complete, modular timelapse system for low power computers backed by a server",
    # long_description_content_type="text/markdown",
    url="https://github.com/brettbeeson/tmv",
    packages=setuptools.find_packages(),
    # "tmv-video-server=tmv.camera:main",
    entry_points={
        'console_scripts': [
            "tmv-camera=tmv.camera:camera_console",
            "tmv-video-compile=tmv.video:video_compile_console",
            "tmv-video-join=tmv.video:video_join_console",
            "tmv-video-info=tmv.videotools:video_info_console",
            "tmv-videod=tmv.videod:videod_console",
            "tmv-video-decompile=tmv.videotools:video_decompile_console",
            "tmv-image-tools=tmv.images:image_tools_console",
            "tmv-influx-stats=tmv.util:influx_stats_console",
            "tmv-s3-upload=tmv.transfer:s3_upload_console",
            "tmv-controller=tmv.controller:controller_console",
            "tmv-control = tmv.controller:control_console",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=['astral', 'toml', 'python-dateutil',
                      'Pillow', 'watchdog', 'boto3', 'freezegun', 'nptime'],
    python_requires='>=3.6',
    extras_require=extras,

)
