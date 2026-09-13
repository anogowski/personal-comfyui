import argparse
import json
import os


PICKER_SLOT_COUNT = 16


def find_workflow_node(workflow, node_id):
	for node in workflow.get("nodes", []):
		if node.get("id") == node_id:
			return node
	raise ValueError(f"Workflow node {node_id} was not found.")


def remove_workflow_links(workflow, link_ids):
	link_ids = set(link_ids)
	if not link_ids:
		return

	workflow["links"] = [link for link in workflow.get("links", []) if link[0] not in link_ids]
	for node in workflow.get("nodes", []):
		for input_slot in node.get("inputs", []):
			if input_slot.get("link") in link_ids:
				input_slot["link"] = None
		for output_slot in node.get("outputs", []):
			links = output_slot.get("links")
			if isinstance(links, list):
				output_slot["links"] = [link_id for link_id in links if link_id not in link_ids]


def remove_node_links(workflow, node_id):
	removed_link_ids = {
		link[0]
		for link in workflow.get("links", [])
		if len(link) >= 4 and (link[1] == node_id or link[3] == node_id)
	}
	remove_workflow_links(workflow, removed_link_ids)
	return removed_link_ids


def find_workflow_input_index(workflow, node_id, input_name):
	node = find_workflow_node(workflow, node_id)
	for index, input_slot in enumerate(node.get("inputs", [])):
		if input_slot.get("name") == input_name:
			return index
	raise ValueError(f"Workflow node {node_id} has no input named '{input_name}'.")


def set_workflow_input_link(workflow, node_id, input_name, link_id):
	node = find_workflow_node(workflow, node_id)
	for input_slot in node.get("inputs", []):
		if input_slot.get("name") == input_name:
			old_link_id = input_slot.get("link")
			if old_link_id is not None:
				remove_workflow_links(workflow, {old_link_id})
			input_slot["link"] = link_id
			return
	raise ValueError(f"Workflow node {node_id} has no input named '{input_name}'.")


def dynamic_image_node(node_id, image_paths, image_link_ids, filename_link_ids, preview_link_id, order):
	picker_paths = image_paths[:PICKER_SLOT_COUNT]
	path_text = "\n".join(image_paths[PICKER_SLOT_COUNT:])
	input_slots = [{
		"localized_name": "image_paths",
		"name": "image_paths",
		"type": "STRING",
		"widget": {"name": "image_paths"},
		"link": None,
	}]
	input_slots.extend({
		"localized_name": f"image_{index}",
		"name": f"image_{index}",
		"type": "COMBO",
		"widget": {"name": f"image_{index}"},
		"link": None,
	} for index in range(1, PICKER_SLOT_COUNT + 1))
	return {
		"id": node_id,
		"type": "DynamicImageList",
		"pos": [-1591.1647757816695, 255.7613845339453],
		"size": [420, 600],
		"flags": {},
		"order": order,
		"mode": 0,
		"inputs": input_slots,
		"outputs": [
			{
				"localized_name": "IMAGE",
				"name": "IMAGE",
				"type": "IMAGE",
				"slot_index": 0,
				"links": image_link_ids + [preview_link_id],
			},
			{
				"localized_name": "FILENAME",
				"name": "FILENAME",
				"type": "STRING",
				"slot_index": 1,
				"links": filename_link_ids,
			},
		],
		"properties": {"Node name for S&R": "DynamicImageList"},
		"widgets_values": [path_text] + picker_paths + [""] * (PICKER_SLOT_COUNT - len(picker_paths)),
		"widgets_values_named": {
			"image_paths": path_text,
			**{
				f"image_{index}": picker_paths[index - 1] if index <= len(picker_paths) else ""
				for index in range(1, PICKER_SLOT_COUNT + 1)
			},
		},
	}


def preview_image_node(node_id, image_link_id, order):
	return {
		"id": node_id,
		"type": "PreviewImage",
		"pos": [-1190, 255],
		"size": [230, 270],
		"flags": {},
		"order": order,
		"mode": 0,
		"inputs": [{
			"localized_name": "images",
			"name": "images",
			"type": "IMAGE",
			"link": None,
		}],
		"outputs": [{
			"localized_name": "images",
			"name": "images",
			"type": "IMAGE",
			"links": [],
		}],
		"properties": {"Node name for S&R": "PreviewImage"},
	}


def _existing_image_paths(node):
	widgets_named = node.get("widgets_values_named", {})
	if node.get("type") != "DynamicImageList":
		return node.get("widgets_values", [])[:1]

	picker_paths = [
		widgets_named.get(f"image_{index}", "")
		for index in range(1, PICKER_SLOT_COUNT + 1)
	]
	path_text = widgets_named.get(
		"image_paths",
		node.get("widgets_values", [""])[0],
	)
	return picker_paths + path_text.splitlines()


def rewrite_workflow(workflow_path, output_path, image_paths=None):
	with open(workflow_path, "r", encoding="utf-8") as workflow_file:
		workflow = json.load(workflow_file)

	old_input_node = next((node for node in workflow.get("nodes", []) if node.get("id") == 1), None)
	if old_input_node is None:
		old_input_node = next(
			(node for node in workflow.get("nodes", []) if node.get("type") == "DynamicImageList"),
			None,
		)
	if old_input_node is None:
		raise ValueError("Workflow must contain node 1 or an existing DynamicImageList node.")

	for required_node_id in (21, 46, 48, 50, 65, 96, 129):
		find_workflow_node(workflow, required_node_id)

	if image_paths is None:
		image_paths = _existing_image_paths(old_input_node)
	elif isinstance(image_paths, str):
		image_paths = image_paths.splitlines()
	else:
		image_paths = [path for value in image_paths for path in str(value).splitlines()]

	image_paths = [path.strip() for path in image_paths if path.strip()]
	if not image_paths:
		raise ValueError("At least one image path is required to rewrite the workflow.")

	old_input_node_id = old_input_node["id"]
	old_node_links = [
		link for link in workflow.get("links", [])
		if len(link) >= 4 and (link[1] == old_input_node_id or link[3] == old_input_node_id)
	]
	removed_link_ids = remove_node_links(workflow, old_input_node_id)
	removed_node_ids = {old_input_node_id}
	for link in old_node_links:
		if link[0] in removed_link_ids and link[3] not in (46, 48, 50, 65, 96, 129):
			removed_node_ids.add(link[3])
	workflow["nodes"] = [node for node in workflow.get("nodes", []) if node.get("id") not in removed_node_ids]

	last_node_id = max(
		int(workflow.get("last_node_id", 0)),
		*(int(node["id"]) for node in workflow.get("nodes", [])),
	)
	dynamic_node_id = last_node_id + 1
	preview_node_id = dynamic_node_id + 1

	last_link_id = max(
		int(workflow.get("last_link_id", 0)),
		*(int(link[0]) for link in workflow.get("links", [])),
	)
	link_specs = []
	for target_node_id, target_input_name in (
		(96, "image"),
		(65, "image"),
		(129, "image"),
	):
		last_link_id += 1
		link_specs.append((last_link_id, 0, target_node_id, target_input_name, "IMAGE"))
	image_link_ids = [spec[0] for spec in link_specs]

	for target_node_id, target_input_name in (
		(46, "filename_prefix"),
		(48, "filename_prefix"),
		(50, "filename_prefix"),
	):
		last_link_id += 1
		link_specs.append((last_link_id, 1, target_node_id, target_input_name, "STRING"))
	filename_link_ids = [spec[0] for spec in link_specs[3:]]
	last_link_id += 1
	preview_link_id = last_link_id

	workflow["nodes"].append(dynamic_image_node(
		dynamic_node_id,
		image_paths,
		image_link_ids,
		filename_link_ids,
		preview_link_id,
		old_input_node.get("order", 0),
	))
	workflow["nodes"].append(preview_image_node(
		preview_node_id,
		preview_link_id,
		old_input_node.get("order", 0) + 1,
	))

	for link_id, source_slot, target_node_id, target_input_name, link_type in link_specs:
		set_workflow_input_link(workflow, target_node_id, target_input_name, link_id)
		workflow.setdefault("links", []).append([
			link_id,
			dynamic_node_id,
			source_slot,
			target_node_id,
			find_workflow_input_index(workflow, target_node_id, target_input_name),
			link_type,
		])

	set_workflow_input_link(workflow, preview_node_id, "images", preview_link_id)
	workflow.setdefault("links", []).append([
		preview_link_id,
		dynamic_node_id,
		0,
		preview_node_id,
		find_workflow_input_index(workflow, preview_node_id, "images"),
		"IMAGE",
	])

	workflow["last_node_id"] = preview_node_id
	workflow["last_link_id"] = last_link_id
	output_directory = os.path.dirname(os.path.abspath(output_path))
	os.makedirs(output_directory, exist_ok=True)
	with open(output_path, "w", encoding="utf-8") as workflow_file:
		json.dump(workflow, workflow_file, indent=2)
		workflow_file.write("\n")
	return workflow


def main():
	parser = argparse.ArgumentParser(description="Add Dynamic Image List to a ComfyUI workflow.")
	parser.add_argument("workflow_path")
	parser.add_argument("image_paths", nargs="+")
	parser.add_argument("--output", dest="output_path")
	arguments = parser.parse_args()
	output_path = arguments.output_path or arguments.workflow_path
	rewrite_workflow(arguments.workflow_path, output_path, arguments.image_paths)


if __name__ == "__main__":
	main()
