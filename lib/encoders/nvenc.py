#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
    plugins.nvenc.py

    Written by:               Josh.5 <jsunnex@gmail.com>
    Date:                     27 Dec 2023, (11:21 AM)

    Copyright:
        Copyright (C) 2021 Josh Sunnex

        This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
        Public License as published by the Free Software Foundation, version 3.

        This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the
        implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
        for more details.

        You should have received a copy of the GNU General Public License along with this program.
        If not, see <https://www.gnu.org/licenses/>.

"""
import logging
import re
import subprocess

logger = logging.getLogger("Unmanic.Plugin.video_transcoder")


def list_available_cuda_devices():
    """
    Return a list of available cuda decoder devices
    :return:
    """
    gpu_dicts = []

    try:
        # Run the nvidia-smi command
        result = subprocess.check_output(['nvidia-smi', '-L'], encoding='utf-8')

        # Use regular expression to find device IDs, names, and UUIDs
        gpu_info = re.findall(r'GPU (\d+): (.+) \(UUID: (.+)\)', result)

        # Populate the list of dictionaries for each GPU
        for gpu_id, gpu_name, gpu_uuid in gpu_info:
            gpu_dict = {
                'hwaccel_device':      gpu_id,
                'hwaccel_device_name': f"{gpu_name} (UUID: {gpu_uuid})"
            }
            gpu_dicts.append(gpu_dict)
    except FileNotFoundError:
        # nvidia-smi executable not found
        return []
    except subprocess.CalledProcessError:
        # nvidia-smi command failed, likely no NVIDIA GPU present
        return []

    # Return the list of GPUs
    return gpu_dicts


class NvencEncoder:
    encoders = [
        "h264_nvenc",
        "hevc_nvenc",
    ]

    def __init__(self, settings):
        self.settings = settings

    @staticmethod
    def options():
        return {
            "nvenc_device":                        "none",
            "nvenc_decoding_method":               "cpu",
            "nvenc_preset":                        "p4",
            "nvenc_tune":                          "auto",
            "nvenc_profile":                       "main",
            "pixel_format":                        "auto",
            "nvenc_encoder_ratecontrol_method":    "auto",
            "nvenc_encoder_ratecontrol_lookahead": 0,
            "enable_spatial_aq":                   False,
            "enable_temporal_aq":                  False,
            "aq_strength":                         8,
        }

    @staticmethod
    def generate_default_args(settings):
        """
        Generate a list of args for using a NVENC decoder

        REF: https://trac.ffmpeg.org/wiki/HWAccelIntro#NVDECCUVID

        :param settings:
        :return:
        """
        # Set the hardware device
        hardware_devices = list_available_cuda_devices()
        if not hardware_devices:
            # Return no options. No hardware device was found
            raise Exception("No VAAPI device found")

        hardware_device = None
        # If we have configured a hardware device
        if settings.get_setting('nvenc_device') not in ['none']:
            # Attempt to match to that configured hardware device
            for hw_device in hardware_devices:
                if settings.get_setting('nvenc_device') == hw_device.get('hwaccel_device'):
                    hardware_device = hw_device
                    break
        # If no matching hardware device is set, then select the first one
        if not hardware_device:
            hardware_device = hardware_devices[0]

        generic_kwargs = {}
        advanced_kwargs = {}
        # Check if we are using a HW accelerated decoder also
        if settings.get_setting('nvenc_decoding_method') != 'cpu':
            generic_kwargs = {
                "-hwaccel":          settings.get_setting('enabled_hw_decoding'),
                "-hwaccel_device":   hardware_device,
                "-init_hw_device":   "{}=hw".format(settings.get_setting('enabled_hw_decoding')),
                "-filter_hw_device": "hw",
            }
        return generic_kwargs, advanced_kwargs

    @staticmethod
    def generate_filtergraphs():
        """
        Generate the required filter for enabling QSV HW acceleration

        :return:
        """
        return ["hwupload_cuda"]

    def args(self, stream_id):
        stream_encoding = []

        # Use defaults for basic mode
        if self.settings.get_setting('mode') in ['basic']:
            defaults = self.options()
            # Use default LA_ICQ mode
            stream_encoding += [
                '-preset', str(defaults.get('nvenc_preset')),
                '-profile:v:{}'.format(stream_id), str(defaults.get('nvenc_profile')),
            ]
            return stream_encoding

        # Add the preset and tune
        if self.settings.get_setting('nvenc_preset'):
            stream_encoding += ['-preset', str(self.settings.get_setting('nvenc_preset'))]
        if self.settings.get_setting('nvenc_tune'):
            stream_encoding += ['-tune', str(self.settings.get_setting('nvenc_tune'))]
        if self.settings.get_setting('nvenc_tune'):
            stream_encoding += ['-profile:v:{}'.format(stream_id), str(self.settings.get_setting('nvenc_profile'))]

        # Apply rate control config
        if self.settings.get_setting('nvenc_encoder_ratecontrol_method', 'auto') != 'auto':
            # Set the rate control method
            stream_encoding += [
                '-rc:v:{}'.format(stream_id), str(self.settings.get_setting('nvenc_encoder_ratecontrol_method'))
            ]
        if self.settings.get_setting('nvenc_encoder_ratecontrol_lookahead'):
            # Set the rate control lookahead frames
            stream_encoding += [
                '-rc-lookahead:v:{}'.format(stream_id), str(self.settings.get_setting('nvenc_encoder_ratecontrol_lookahead'))
            ]

        # Apply adaptive quantization
        if self.settings.get_setting('enable_spatial_aq'):
            stream_encoding += ['-spatial-aq', '1']
        if self.settings.get_setting('enable_temporal_aq'):
            stream_encoding += ['-temporal-aq', '1']
        if self.settings.get_setting('enable_spatial_aq') or self.settings.get_setting('enable_temporal_aq'):
            stream_encoding += ['-aq-strength:v:{}'.format(stream_id), str(self.settings.get_setting('aq_strength'))]

        return stream_encoding

    def __set_default_option(self, select_options, key, default_option=None):
        """
        Sets the default option if the currently set option is not available

        :param select_options:
        :param key:
        :return:
        """
        available_options = []
        for option in select_options:
            available_options.append(option.get('value'))
            if not default_option:
                default_option = option.get('value')
        if self.settings.get_setting(key) not in available_options:
            self.settings.set_setting(key, default_option)

    def get_nvenc_device_form_settings(self):
        values = {
            "label":          "NVIDIA Device",
            "sub_setting":    True,
            "input_type":     "select",
            "select_options": [
                {
                    "value": "none",
                    "label": "No NVIDIA devices available",
                }
            ]
        }
        default_option = None
        hardware_devices = list_available_cuda_devices()
        if hardware_devices:
            values['select_options'] = []
            for hw_device in hardware_devices:
                if not default_option:
                    default_option = hw_device.get('hwaccel_device', 'none')
                values['select_options'].append({
                    "value": hw_device.get('hwaccel_device', 'none'),
                    "label": "NVIDIA device '{}'".format(hw_device.get('hwaccel_device_path', 'not found')),
                })
        if not default_option:
            default_option = 'none'

        self.__set_default_option(values['select_options'], 'nvenc_device', default_option=default_option)
        if self.settings.get_setting('mode') not in ['standard']:
            values["display"] = "hidden"
        return values

    def get_nvenc_decoding_method_form_settings(self):
        values = {
            "label":          "Enable HW Decoding",
            "description":    "Warning. Ensure your device supports decoding the source video codec or it will fail.",
            "sub_setting":    True,
            "input_type":     "select",
            "select_options": [
                {
                    "value": "cpu",
                    "label": "Disabled - Use CPU to decode of video source (provides best compatibility)",
                },
                {
                    "value": "cuda",
                    "label": "CUDA - Use NVIDIA CUDA for decoding the video source (best compatibility with older GPUs)",
                },
                {
                    "value": "nvdec",
                    "label": "NVDEC - Use the GPUs dedicated video decoder",
                }
            ]
        }
        if self.settings.get_setting('mode') not in ['standard']:
            values["display"] = "hidden"
        return values

    def get_nvenc_preset_form_settings(self):
        values = {
            "label":          "Encoder quality preset",
            "sub_setting":    True,
            "input_type":     "select",
            "select_options": [
                {
                    "value": "p1",
                    "label": "Fastest (P1)",
                },
                {
                    "value": "p2",
                    "label": "Faster (P2)",
                },
                {
                    "value": "p3",
                    "label": "Fast (P3)",
                },
                {
                    "value": "p4",
                    "label": "Medium (P4) - Balanced performance and quality",
                },
                {
                    "value": "p5",
                    "label": "Slow (P5)",
                },
                {
                    "value": "p6",
                    "label": "Slower (P6)",
                },
                {
                    "value": "p7",
                    "label": "Slowest (P7)",
                },
            ],
        }
        self.__set_default_option(values['select_options'], 'nvenc_preset', default_option='p4')
        if self.settings.get_setting('mode') not in ['standard']:
            values["display"] = "hidden"
        return values

    def get_nvenc_tune_form_settings(self):
        values = {
            "label":          "Tune for a particular type of source or situation",
            "sub_setting":    True,
            "input_type":     "select",
            "select_options": [
                {
                    "value": "auto",
                    "label": "Disabled – Do not apply any tune",
                },
                {
                    "value": "hq",
                    "label": "HQ – High quality (ffmpeg default)",
                },
                {
                    "value": "ll",
                    "label": "LL – Low latency",
                },
                {
                    "value": "ull",
                    "label": "ULL – Ultra low latency",
                },
                {
                    "value": "lossless",
                    "label": "Lossless",
                },
            ],
        }
        self.__set_default_option(values['select_options'], 'nvenc_tune', default_option='auto')
        if self.settings.get_setting('mode') not in ['standard']:
            values["display"] = "hidden"
        return values

    def get_nvenc_profile_form_settings(self):
        values = {
            "label":          "Profile",
            "description":    "The profile determines which features of the codec are available and enabled,\n"
                              "while also affecting other restrictions.\n"
                              "Any of these profiles are capable of 4:2:0, 4:2:2 and 4:4:4, however the support\n"
                              "depends on the installed hardware.",
            "sub_setting":    True,
            "input_type":     "select",
            "select_options": [
                {
                    "value": "auto",
                    "label": "Auto – Let ffmpeg automatically select the required profile (recommended)",
                },
                {
                    "value": "baseline",
                    "label": "Baseline",
                },
                {
                    "value": "main",
                    "label": "Main",
                },
                {
                    "value": "high",
                    "label": "High",
                },
                {
                    "value": "high444p",
                    "label": "High444p",
                },
            ],
        }
        self.__set_default_option(values['select_options'], 'nvenc_profile', default_option='main')
        if self.settings.get_setting('mode') not in ['standard']:
            values["display"] = "hidden"
        return values

    def get_pixel_format_form_settings(self):
        values = {
            "label":          "Encoder pixel format",
            "description":    "Note: If you get the 'No NVENC capable devices found' error make sure you're \n"
                              "encoding to a supported pixel format for the hardware and ffmpeg version.\n"
                              "Any of these profiles are capable of 4:2:0, 4:2:2 and 4:4:4, however the support\n"
                              "depends on the installed hardware.",
            "sub_setting":    True,
            "input_type":     "select",
            "select_options": [
                {
                    "value": "auto",
                    "label": "Auto – Let ffmpeg automatically select the required pixel format (recommended)",
                },
                {
                    "value": "yuv420p",
                    "label": "yuv420p - 4:2:0 chroma subsampling (commonly used in H.264)",
                },
                {
                    "value": "yuv422p",
                    "label": "yuv422p - 4:2:2 chroma subsampling",
                },
                {
                    "value": "yuv444p",
                    "label": "yuv444p - 4:4:4 chroma subsampling, no subsampling",
                },
                {
                    "value": "nv12",
                    "label": "nv12 - A variation of YUV 4:2:0 with a different layout, often used in hardware-accelerated encoding paths",
                },
                {
                    "value": "p010le",
                    "label": "p010le - A 10-bit YUV 4:2:0 format, often used for high dynamic range (HDR) content",
                },
                {
                    "value": "p016le",
                    "label": "p016le - A 10-bit version of YUV 4:2:0, similar to p010le but with different bit depth handling",
                },
                {
                    "value": "yuv420p10le",
                    "label": "yuv420p10le - A 10-bit version of YUV 4:2:0",
                },
                {
                    "value": "yuv444p16le",
                    "label": "yuv444p16le - A 16-bit version of YUV 4:4:4, offering very high color fidelity",
                },
            ]
        }
        self.__set_default_option(values['select_options'], 'pixel_format', default_option='auto')
        if self.settings.get_setting('mode') not in ['standard']:
            values["display"] = "hidden"
        return values

    def get_nvenc_encoder_ratecontrol_method_form_settings(self):
        values = {
            "label":          "Encoder ratecontrol method",
            "description":    "Note that the rate control is already defined in the Encoder Quality Preset option.\n"
                              "Selecting anything other than 'Disabled' will override the preset rate-control.",
            "sub_setting":    True,
            "input_type":     "select",
            "select_options": [
                {
                    "value": "auto",
                    "label": "Disabled – Do not override the RC setting pre-defined in the preset option (recommended)",
                },
                {
                    "value": "constqp",
                    "label": "CQP - Quality based mode using constant quantizer scale",
                },
                {
                    "value": "vbr",
                    "label": "VBR - Bitrate based mode using variable bitrate",
                },
                {
                    "value": "vbr_hq",
                    "label": "VBR HQ - High Quality VBR mode",
                },
                {
                    "value": "cbr",
                    "label": "CBR - Bitrate based mode using constant bitrate",
                },
                {
                    "value": "cbr_hq",
                    "label": "CBR HQ - High Quality CBR mode",
                },
            ]
        }
        self.__set_default_option(values['select_options'], 'nvenc_encoder_ratecontrol_method', default_option='auto')
        if self.settings.get_setting('mode') not in ['standard']:
            values["display"] = "hidden"
        return values

    def get_nvenc_encoder_ratecontrol_lookahead_form_settings(self):
        # Lower is better
        values = {
            "label":          "Configure the number of frames to look ahead for rate-control",
            "sub_setting":    True,
            "input_type":     "slider",
            "slider_options": {
                "min": 0,
                "max": 30,
            },
        }
        if self.settings.get_setting('mode') not in ['standard']:
            values["display"] = "hidden"
        return values

    def get_enable_spatial_aq_form_settings(self):
        values = {
            "label":       "Enable Spatial Adaptive Quantization",
            "description": "This adjusts the quantization parameter within each frame based on spatial complexity.\n"
                           "This helps in improving the quality of areas within a frame that are more detailed or complex.",
            "sub_setting": True,
        }
        if self.settings.get_setting('mode') not in ['standard']:
            values["display"] = 'hidden'
        return values

    def get_enable_temporal_aq_form_settings(self):
        values = {
            "label":       "Enable Temporal Adaptive Quantization",
            "description": "This adjusts the quantization parameter across frames, based on the motion and temporal complexity.\n"
                           "This is particularly effective in scenes with varying levels of motion, enhancing quality where it's most needed.",
            "sub_setting": True,
        }
        if self.settings.get_setting('mode') not in ['standard']:
            values["display"] = 'hidden'
        return values

    def get_aq_strength_form_settings(self):
        # Lower is better
        values = {
            "label":          "Strength of the adaptive quantization",
            "description":    "Controls the strength of the adaptive quantization (both spatial and temporal).\n"
                              "A higher value indicates stronger adaptation, which can lead to better preservation\n"
                              "of detail but might also increase the bitrate.",
            "sub_setting":    True,
            "input_type":     "slider",
            "slider_options": {
                "min": 0,
                "max": 15,
            },
        }
        if self.settings.get_setting('mode') not in ['standard']:
            values["display"] = "hidden"
        if not self.settings.get_setting('enable_spatial_aq') and not self.settings.get_setting('enable_temporal_aq'):
            values["display"] = "hidden"
        return values