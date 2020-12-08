import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

    # don't work: see below
    extras = {
        'advanced': ['ascii_graph', 'datetimerange', 'psutil'],
        'web': ['Flask', 'flask-socketio']
    }

setuptools.setup(
    name="timemv",
    version="0.0.2",
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
            "tmv-buttons = tmv.camera:buttons_console",
            "tmv-video-compile=tmv.video:video_compile_console",
            "tmv-video-join=tmv.video:video_join_console",
            "tmv-video-info=tmv.videotools:video_info_console",
            "tmv-videod=tmv.videod:videod_console",
            "tmv-video-decompile=tmv.videotools:video_decompile_console",
            "tmv-image-tools=tmv.images:image_tools_console",
            "tmv-influx-stats=tmv.util:influx_stats_console",
            "tmv-upload=tmv.upload:upload_console",   
            "tmv-tunnel = tmv.tunnel:tunnel_console",
            "tmv-interface = tmv.interface.app:interface_console"
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    # can't get extras to work: just install 'em
    #extras_require=extras

    # todo: change from boto to minio. boto is massive
    # 'psutil'
    # 'sshconf'
    install_requires=['astral', 'toml', 'python-dateutil', 'pytimeparse',
                      'Pillow', 'watchdog', 'boto3', 'freezegun', 'nptime', 
                      'Flask', 'flask-socketio','ascii_graph', 'datetimerange', 'gpiozero'],

    python_requires='>=3.6',

    

)
