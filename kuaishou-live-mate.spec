# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 - 旁白

使用方法: python -m PyInstaller kuaishou-live-mate.spec
输出: dist/旁白/旁白.exe (onedir模式，启动快)
"""

import os
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config.example.yaml', '.'),
        ('src/kuaishou_pb2.py', 'src'),
        ('logo.png', '.'),
        # SenseVoiceSmall ONNX 模型文件
        (os.path.join(os.path.expanduser('~'), '.cache', 'modelscope', 'models',
                      'manyeyes--sensevoice-small-onnx', 'snapshots', 'master', 'model.onnx'),
         os.path.join('models', 'sensevoice')),
        (os.path.join(os.path.expanduser('~'), '.cache', 'modelscope', 'models',
                      'manyeyes--sensevoice-small-onnx', 'snapshots', 'master', 'am.mvn'),
         os.path.join('models', 'sensevoice')),
        (os.path.join(os.path.expanduser('~'), '.cache', 'modelscope', 'models',
                      'manyeyes--sensevoice-small-onnx', 'snapshots', 'master', 'config.yaml'),
         os.path.join('models', 'sensevoice')),
        (os.path.join(os.path.expanduser('~'), '.cache', 'modelscope', 'models',
                      'manyeyes--sensevoice-small-onnx', 'snapshots', 'master', 'chn_jpn_yue_eng_ko_spectok.bpe.model'),
         os.path.join('models', 'sensevoice')),
        (os.path.join(os.path.expanduser('~'), '.cache', 'modelscope', 'models',
                      'manyeyes--sensevoice-small-onnx', 'snapshots', 'master', 'tokens.json'),
         os.path.join('models', 'sensevoice')),
    ],
    hiddenimports=[
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'playwright',
        'playwright.async_api',
        'funasr_onnx',
        'funasr_onnx.utils',
        'funasr_onnx.utils.utils',
        'funasr_onnx.utils.frontend',
        'funasr_onnx.utils.sentencepiece_tokenizer',
        'jieba',
        'kaldi_native_fbank',
        'sentencepiece',
        'google.protobuf',
        'google.protobuf.json_format',
        'openai',
        'yaml',
        'numpy',
        'librosa',
        'sklearn',
        'sklearn.cluster',
        'urllib.request',
        # v1.1.0 新增：平台抽象层
        'src.platforms',
        'src.platforms.base',
        'src.platforms.kuaishou',
        'src.platforms.douyin',
        'src.platforms.registry',
        'src.engine_manager',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='旁白',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 不显示控制台黑框，只显示GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app.ico',
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='旁白',
)
