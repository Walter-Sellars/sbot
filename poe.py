#!/usr/bin/env python3

import json
import re
import time
import urllib.parse

import requests

rs = requests.Session()

league_name = None

def price(cmd):
	global league_name

	if league_name is None:
		league_name = _get_league_name()

	if not cmd.args:
		return
	names, lines = _search(league_name, cmd.args)
	if len(names) == 0:
		cmd.reply("couldn't find " + cmd.args)
	elif len(names) > 1:
		cmd.reply(', '.join(names)[:250])
	else:
		responses = [league_name + ':']
		for line in lines:
			name = line['name']
			if line['links'] > 0:
				name += ' (%d link)' % line['links']
			response = '%s: %.1f chaos' % (name, line['chaosValue'])
			if line['exaltedValue'] > 1.0:
				response += ', %.1f exalted' % line['exaltedValue']
			responses.append(response)
		cmd.reply('\n'.join(responses))

def _get_league_name():
	html = rs.get('https://poe.ninja/')
	prefix = 'window.leagues = '
	for line in html.text.split('\n'):
		if prefix in line:
			start = line.index(prefix) + len(prefix)
			end = line.find('];</script>') + 1
			doc = line[start:end]
			break
	else:
		raise Exception("Couldn't find leagues JSON")

	leagues = json.loads(doc)
	standard_league = None
	for league_info in leagues:
		if league_info['url'] == 'challenge':
			return league_info['name']
		elif league_info['url'] == 'standard':
			standard_league = league_info['name']
	return standard_league

pages = [
	'UniqueArmour',
	'UniqueWeapon',
	'UniqueAccessory',
	'UniqueJewel',
	'UniqueFlask',
	'UniqueMap',
	'DivinationCard',
	'Prophecy',
	'HelmetEnchant',
]

def _search(league, q):
	q = q.casefold()
	names = set()
	matches = []
	for page in pages:
		data = _query(page, league)
		lines = data['lines']
		for line in lines:
			if q in line['name'].casefold():
				names.add(line['name'])
				matches.append(line)
		if len(names) > 0:
			# there may be other matches on other pages, but we won't bother finding them
			break
	return names, matches

cache = {}

def _query(page, league):
	cached = cache.get((page, league))
	now = time.time()
	if cached is not None:
		ts, data = cached
		if ts > now - 60 * 60: # cache for 1 hour
			return data

	data = rs.get('https://poe.ninja/api/data/itemoverview?league=%s&type=%s' % (league, page)).json()
	cache[(page, league)] = now, data
	return data

class PageValuesException(Exception):
	pass

def wiki(cmd):
	if not cmd.args:
		return

	r = rs.get('https://pathofexile.gamepedia.com/api.php',
		headers={'Accept': 'application/json'},
		params={
			'action': 'opensearch',
			'format': 'json',
			'formatversion': '2',
			'search': cmd.args,
			'limit': 10,
		})
	r.raise_for_status()
	query, results, _, urls = r.json()
	if len(results) == 0:
		cmd.reply('no results found for %r' % query)
		return
	elif len(results) > 1:
		cmd.reply(', '.join(results))
		return
	[page_name] = results
	page_name = page_name.replace(' ', '_')

	r = rs.get('https://pathofexile.gamepedia.com/index.php', params={'title': page_name, 'action': 'pagevalues'})
	r.raise_for_status()
	try:
		item_info = _parse_pagevalues(results[0], r.text)
	except PageValuesException as e:
		cmd.reply(e.args[0])
		return

	requirements = []
	if item_info['required_level_range_text']:
		requirements.append('Requires Level ' + item_info['required_level_range_text'])
	if item_info['required_dexterity_range_text']:
		requirements.append(item_info['required_dexterity_range_text'] + ' Dex')
	if item_info['required_intelligence_range_text']:
		requirements.append(item_info['required_intelligence_range_text'] + ' Int')
	if item_info['required_strength_range_text']:
		requirements.append(item_info['required_strength_range_text'] + ' Str')
	desc = '\n\n'.join(filter(None, [
		', '.join(requirements), item_info['implicit_stat_text'], item_info['explicit_stat_text']
	]))
	cmd.reply('', {
		'title': results[0],
		'description': desc,
		'url': urls[0],
		'image': {'url': item_info['inventory_icon']},
	})

def _parse_pagevalues(name, pagevalues):
	item_info = dict.fromkeys([
		'implicit_stat_text', 'explicit_stat_text',
		'required_level_range_text',
		'required_dexterity_range_text', 'required_intelligence_range_text', 'required_strength_range_text',
		'inventory_icon',
	])
	for line in pagevalues.split('\n'):
		if 'implicit_stat_text' in line:
			start_text = '<table class="wikitable mw-page-info"><tr><td style="vertical-align: top;">'
			end_text = '</tr></table>'
			if not line.startswith(start_text) or not line.endswith(end_text):
				raise PageValuesException('failed to parse pagevalues for %s' % name)
			line = line[len(start_text):-len(end_text)]
			cells = line.split('</td></tr><tr><td style="vertical-align: top;">')
			for cell in cells:
				key, value = cell.split('</td><td>', 2)
				if key in item_info:
					item_info[key] = _strip_mediawiki_formatting(value)
			break
	else:
		raise PageValuesException('%s is not equippable' % name)

	for key, value in item_info.items():
		if key.startswith('required_') and value == '0':
			item_info[key] = None

	inventory_icon = item_info['inventory_icon']
	assert inventory_icon.startswith('File:')
	inventory_icon = inventory_icon[len('File:'):] # pylint: disable=unsubscriptable-object
	r = rs.head('https://pathofexile.gamepedia.com/Special:Redirect/file/' +
			urllib.parse.quote(inventory_icon.replace(' ', '_')))
	r.raise_for_status()
	item_info['inventory_icon'] = r.headers['Location']

	return item_info

def _strip_mediawiki_formatting(value):
	lines = []
	for line in value.split('&lt;br&gt;'):
		if line.startswith('&lt;'):
			line = '[unparsed]'
		lines.append(line)
	value = '\n'.join(lines)
	value = re.sub(r'\[\[(.*\|)?(.+?)\]\]', r'\2', value)
	return value
