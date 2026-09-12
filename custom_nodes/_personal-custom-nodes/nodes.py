import json
import os

import numpy as np
import torch
import folder_paths
from comfy.cli_args import args
from nodes import SaveImage
from PIL import Image, ImageEnhance, ImageFilter, ImageChops, ImageOps
from PIL.PngImagePlugin import PngInfo


def parse_hex_color(s: str):
	s = s.strip().lstrip("#")
	if len(s) not in (6, 8):
		raise ValueError("Color must be RRGGBB or RRGGBBAA (optionally with #).")
	r = int(s[0:2], 16)
	g = int(s[2:4], 16)
	b = int(s[4:6], 16)
	a = int(s[6:8], 16) if len(s) == 8 else 255
	return r, g, b, a


def tensor_to_pil_rgba(image_tensor: torch.Tensor) -> Image.Image:
	image_np = image_tensor.detach().cpu().numpy()
	image_np = np.clip(image_np, 0.0, 1.0)
	image_np = (image_np * 255.0).astype(np.uint8)

	if image_np.ndim != 3:
		raise ValueError("Expected image tensor with shape (H, W, C).")

	if image_np.shape[2] == 3:
		alpha = np.full((image_np.shape[0], image_np.shape[1], 1), 255, dtype=np.uint8)
		image_np = np.concatenate([image_np, alpha], axis=2)
	elif image_np.shape[2] != 4:
		raise ValueError("Expected image with 3 or 4 channels.")

	return Image.fromarray(image_np, mode="RGBA").copy()


def pil_to_tensor(image: Image.Image) -> torch.Tensor:
	image_np = np.array(image).astype(np.float32) / 255.0
	return torch.from_numpy(image_np).unsqueeze(0)


def luminance_above_threshold_mask(rgb: Image.Image, threshold_color: str) -> Image.Image:
	threshold_rgba = parse_hex_color(threshold_color)
	threshold_luminance = int(Image.new("RGB", (1, 1), threshold_rgba[:3]).convert("L").getpixel((0, 0)))
	return rgb.convert("L").point(lambda value: 255 if value > threshold_luminance else 0)


def background_mask(rgb: Image.Image, background_color: str, threshold: int) -> Image.Image:
	background = np.array(parse_hex_color(background_color)[:3], dtype=np.int16)
	pixels = np.array(rgb.convert("RGB"), dtype=np.int16)
	distance = np.max(np.abs(pixels - background), axis=2)
	mask = np.where(distance <= int(threshold), 0, 255).astype(np.uint8)
	return Image.fromarray(mask, mode="L")


class ImageBrightness:
	@classmethod
	def INPUT_TYPES(cls):
		return {
			"required": {
				"image": ("IMAGE",),
				"brightness": ("FLOAT", {"default": 1.35, "min": 0.0, "max": 4.0, "step": 0.05}),
					"dark_threshold": ("STRING", {"default": "#222222"}),
			}
		}

	RETURN_TYPES = ("IMAGE",)
	FUNCTION = "apply"
	CATEGORY = "Image/Adjust"

	def apply(self, image, brightness, dark_threshold):
		outputs = []
		for img in image:
			pil_img = tensor_to_pil_rgba(img)
			original_rgb = pil_img.convert("RGB")
			brightened_rgb = ImageEnhance.Brightness(original_rgb).enhance(float(brightness))
			rgb = Image.composite(brightened_rgb, original_rgb, luminance_above_threshold_mask(original_rgb, dark_threshold))
			rgb.putalpha(pil_img.getchannel("A"))
			outputs.append(pil_to_tensor(rgb))
		return (torch.cat(outputs, dim=0),)


class ImageBlur:
	@classmethod
	def INPUT_TYPES(cls):
		return {
			"required": {
				"image": ("IMAGE",),
				"sigma": ("FLOAT", {"default": 1.25, "min": 0.1, "max": 4.0, "step": 0.05}),
			}
		}

	RETURN_TYPES = ("IMAGE",)
	FUNCTION = "apply"
	CATEGORY = "Image/Adjust"

	def apply(self, image, sigma):
		outputs = []
		for img in image:
			blurred = tensor_to_pil_rgba(img).filter(ImageFilter.GaussianBlur(radius=float(sigma)))
			if img.shape[-1] == 3:
				blurred = blurred.convert("RGB")
			outputs.append(pil_to_tensor(blurred))
		return (torch.cat(outputs, dim=0),)


class ImageSharpen:
	@classmethod
	def INPUT_TYPES(cls):
		return {
			"required": {
				"image": ("IMAGE",),
				"strength": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 2.0, "step": 0.05}),
			}
		}

	RETURN_TYPES = ("IMAGE",)
	FUNCTION = "apply"
	CATEGORY = "Image/Adjust"

	def apply(self, image, strength):
		outputs = []
		percent = int(round(float(strength) * 100.0))
		for img in image:
			sharpened = tensor_to_pil_rgba(img).filter(
				ImageFilter.UnsharpMask(radius=1.0, percent=percent, threshold=1)
			)
			if img.shape[-1] == 3:
				sharpened = sharpened.convert("RGB")
			outputs.append(pil_to_tensor(sharpened))
		return (torch.cat(outputs, dim=0),)


class DynamicImageList:
	PICKER_SLOT_COUNT = 16
	OUTPUT_IS_LIST = (True, True)

	@classmethod
	def INPUT_TYPES(cls):
		picker_options = cls.picker_options()
		picker_inputs = {
			f"image_{index}": (picker_options, {"image_upload": True})
			for index in range(2, cls.PICKER_SLOT_COUNT + 1)
		}
		return {
			"required": {
				"image_paths": ("STRING", {
					"default": "",
					"multiline": True,
					"dynamicPrompts": False,
				}),
				"image_1": (picker_options, {"image_upload": True}),
			},
			"optional": picker_inputs,
		}

	RETURN_TYPES = ("IMAGE", "STRING")
	RETURN_NAMES = ("IMAGE", "FILENAME")
	FUNCTION = "load_images"
	CATEGORY = "Image/Load"

	@staticmethod
	def picker_options():
		input_directory = folder_paths.get_input_directory()
		files = [
			filename
			for filename in os.listdir(input_directory)
			if os.path.isfile(os.path.join(input_directory, filename))
		]
		try:
			files = folder_paths.filter_files_content_types(files, ["image"])
		except AttributeError:
			pass
		return [""] + sorted(files)

	@staticmethod
	def resolve_path(image_path):
		image_path = image_path.strip()
		if os.path.isabs(image_path):
			resolved_path = os.path.realpath(image_path)
		else:
			try:
				resolved_path = folder_paths.get_annotated_filepath(image_path)
			except ValueError:
				resolved_path = os.path.realpath(image_path)

		if not os.path.isfile(resolved_path):
			raise ValueError(f"Image path does not exist: {image_path}")
		return resolved_path

	def load_images(self, image_paths="", image_1="", **picker_inputs):
		selected_paths = [image_1]
		selected_paths.extend(
			picker_inputs.get(f"image_{index}", "")
			for index in range(2, self.PICKER_SLOT_COUNT + 1)
		)
		paths = []
		for path in selected_paths + image_paths.splitlines():
			path = path.strip()
			if path and path not in paths:
				paths.append(path)
		if not paths:
			raise ValueError("Dynamic Image List requires at least one image path.")

		images = []
		filenames = []
		for image_path in paths:
			resolved_path = self.resolve_path(image_path)
			try:
				with Image.open(resolved_path) as source:
					image = ImageOps.exif_transpose(source).convert("RGBA")
			except (OSError, ValueError) as error:
				raise ValueError(f"Could not load image '{image_path}': {error}") from error

			images.append(pil_to_tensor(image))
			filenames.append(os.path.splitext(os.path.basename(resolved_path))[0])

		return images, filenames


class ImageAuraGlow:
	@classmethod
	def INPUT_TYPES(cls):
		return {
			"required": {
				"image": ("IMAGE",),
					"color": ("STRING", {"default": "#FDDC5C"}),
				"radius": ("INT", {"default": 8, "min": 1, "max": 64, "step": 1}),
				"intensity": ("FLOAT", {"default": 1.25, "min": 0.0, "max": 4.0, "step": 0.05}),
					"dark_threshold": ("STRING", {"default": "#222222"}),
			}
		}

	RETURN_TYPES = ("IMAGE",)
	FUNCTION = "apply"
	CATEGORY = "Image/Effects"

	def apply(self, image, color, radius, intensity, dark_threshold):
		color_rgba = parse_hex_color(color)
		outputs = []
		for img in image:
			pil_img = tensor_to_pil_rgba(img)
			rgb = pil_img.convert("RGB")

			mask = rgb.convert("L").filter(ImageFilter.GaussianBlur(radius=int(radius)))
			mask = ImageEnhance.Brightness(mask).enhance(float(intensity))
			dark_pixels = luminance_above_threshold_mask(rgb, dark_threshold)
			mask = ImageChops.multiply(mask, dark_pixels)
			glow = Image.new("RGB", rgb.size, color_rgba[:3])
			glow = Image.composite(glow, Image.new("RGB", rgb.size, (0, 0, 0)), mask)
			result = ImageChops.screen(rgb, glow)
			result.putalpha(pil_img.getchannel("A"))
			outputs.append(pil_to_tensor(result))
		return (torch.cat(outputs, dim=0),)


class ImageBlackToAlpha:
	@classmethod
	def INPUT_TYPES(cls):
		return {
			"required": {
				"image": ("IMAGE",),
				"threshold": ("STRING", {"default": "#222222"}),
			}
		}

	RETURN_TYPES = ("IMAGE", "MASK")
	RETURN_NAMES = ("IMAGE", "MASK")
	FUNCTION = "apply"
	CATEGORY = "Image/Adjust"

	def apply(self, image, threshold):
		threshold_rgb = parse_hex_color(threshold)[:3]
		images = []
		masks = []
		for img in image:
			pil_img = tensor_to_pil_rgba(img)
			pixels = pil_img.load()
			for y in range(pil_img.height):
				for x in range(pil_img.width):
					r, g, b, _ = pixels[x, y]
					if r <= threshold_rgb[0] and g <= threshold_rgb[1] and b <= threshold_rgb[2]:
						pixels[x, y] = (r, g, b, 0)
			alpha = pil_img.getchannel("A")
			images.append(pil_to_tensor(pil_img))
			masks.append(torch.from_numpy(np.asarray(alpha, dtype=np.float32) / 255.0))
		return torch.cat(images, dim=0), torch.stack(masks, dim=0)


class SaveImageWithAlpha(SaveImage):
	@classmethod
	def INPUT_TYPES(cls):
		inputs = SaveImage.INPUT_TYPES()
		inputs["optional"] = {
			"mask": ("MASK", {"tooltip": "Alpha mask to write into the PNG."}),
		}
		return inputs

	def save_images(self, images, filename_prefix="ComfyUI", mask=None, prompt=None, extra_pnginfo=None):
		filename_prefix += self.prefix_append
		if mask is None:
			images_to_save, _ = ImageBlackToAlpha().apply(images, "#000000")
		else:
			images_to_save = images
		full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(
			filename_prefix, self.output_dir, images[0].shape[1], images[0].shape[0]
		)
		results = []
		for batch_number, image in enumerate(images_to_save):
			pil_img = tensor_to_pil_rgba(image)
			if mask is None:
				alpha = pil_img.getchannel("A")
			else:
				mask_index = min(batch_number, mask.shape[0] - 1)
				mask_np = np.clip(mask[mask_index].detach().cpu().numpy() * 255.0, 0, 255).astype(np.uint8)
				alpha = Image.fromarray(mask_np, mode="L")
				if alpha.size != pil_img.size:
					alpha = alpha.resize(pil_img.size, Image.Resampling.NEAREST)
				alpha = ImageChops.multiply(pil_img.getchannel("A"), alpha)
			pil_img.putalpha(alpha)

			metadata = None
			if not args.disable_metadata:
				metadata = PngInfo()
				if prompt is not None:
					metadata.add_text("prompt", json.dumps(prompt))
				if extra_pnginfo is not None:
					for key in extra_pnginfo:
						metadata.add_text(key, json.dumps(extra_pnginfo[key]))

			filename_with_batch_num = filename.replace("%batch_num%", str(batch_number))
			file = f"{filename_with_batch_num}_{counter:05}_.png"
			pil_img.save(
				os.path.join(full_output_folder, file),
				pnginfo=metadata,
				compress_level=self.compress_level,
			)
			results.append({"filename": file, "subfolder": subfolder, "type": self.type})
			counter += 1

		return {"ui": {"images": results}, "result": (images,)}


NODE_CLASS_MAPPINGS = {
	"DynamicImageList": DynamicImageList,
	"ImageBlur": ImageBlur,
	"ImageBrightness": ImageBrightness,
	"ImageAuraGlow": ImageAuraGlow,
	"ImageBlackToAlpha": ImageBlackToAlpha,
	"ImageSharpen": ImageSharpen,
	"SaveImageWithAlpha": SaveImageWithAlpha,
}

NODE_DISPLAY_NAME_MAPPINGS = {
	"DynamicImageList": "Dynamic Image List",
	"ImageBlur": "Image Blur (Gaussian)",
	"ImageBrightness": "Image Brightness",
	"ImageAuraGlow": "Image Aura Glow",
	"ImageBlackToAlpha": "Image Black To Alpha",
	"ImageSharpen": "Image Sharpen (Unsharp Mask)",
	"SaveImageWithAlpha": "Save Image With Alpha (PNG)",
}
