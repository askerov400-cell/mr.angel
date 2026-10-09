"""Bounded local-only FFmpeg processing; stderr is never logged."""
import asyncio
import math
import re
import subprocess
import sys
from pathlib import Path
import imageio_ffmpeg

MAX_SECONDS = 120
MAX_FRAME_BYTES = 1024 * 1024
MAX_AUDIO_BYTES = 5 * 1024 * 1024

class InvalidVideo(ValueError):
    pass

async def run(*args, timeout=20, probe=False):
    flags = {'creationflags':subprocess.CREATE_NO_WINDOW} if sys.platform=='win32' else {}
    process = await asyncio.create_subprocess_exec(
        imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-nostdin', '-max_alloc', '67108864',
        *map(str,args), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, **flags,
    )
    try:
        async with asyncio.timeout(timeout):
            # Limit metadata/decoder diagnostics, which can contain untrusted text.
            data = bytearray()
            while chunk := await process.stderr.read(4096):
                data.extend(chunk)
                if len(data)>65536:
                    raise InvalidVideo('Oversize decoder diagnostics')
            await process.wait()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode != 0 and not probe:
        raise InvalidVideo('Decoder rejected video')
    return bytes(data).decode('utf-8',errors='replace')

def metadata(diagnostics):
    found = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)',diagnostics)
    if not found or not re.search(r'Stream .*Video:',diagnostics):
        raise InvalidVideo('Missing video metadata')
    duration = int(found[1])*3600+int(found[2])*60+float(found[3])
    if not math.isfinite(duration) or not 0 < duration <= MAX_SECONDS:
        raise InvalidVideo('Video duration outside limit')
    return duration, bool(re.search(r'Stream .*Audio:',diagnostics))

async def extract(path, directory):
    diagnostics = await run('-protocol_whitelist','file,pipe','-format_whitelist','mov,matroska,webm','-i',path,timeout=15,probe=True)
    duration, has_audio = metadata(diagnostics)
    frames = []
    for index, part in enumerate((0.1,0.5,0.9)):
        timestamp = round(duration*part,2)
        output = Path(directory)/f'frame-{index}.jpg'
        await run('-y','-protocol_whitelist','file,pipe','-ss',timestamp,'-threads','1','-format_whitelist','mov,matroska,webm','-i',path,
                  '-map','0:v:0','-frames:v','1','-vf','scale=768:768:force_original_aspect_ratio=decrease',
                  '-threads','1','-q:v','4',output)
        if not output.is_file() or not 0 < output.stat().st_size <= MAX_FRAME_BYTES:
            raise InvalidVideo('Frame outside limit')
        frames.append((timestamp,output.read_bytes()))
    audio = None
    if has_audio:
        audio = Path(directory)/'speech.flac'
        await run('-y','-protocol_whitelist','file,pipe','-threads','1','-format_whitelist','mov,matroska,webm','-i',path,
                  '-map','0:a:0','-vn','-ac','1','-ar','16000','-t',MAX_SECONDS,
                  '-c:a','flac','-threads','1',audio)
        if not audio.is_file() or not 0 < audio.stat().st_size <= MAX_AUDIO_BYTES:
            raise InvalidVideo('Audio outside limit')
    return duration,frames,audio
