"""
"heirloom worth": what the games and DLC in your library cost on the Epic Games Store, at full price and at
today's price, from the store's public prices for your country. A game is priced by its namespace's base game
offer, a DLC by the offer of the same title; games no longer sold are counted apart.
"""
import json

import requests

STORE_API = 'https://store.epicgames.com/graphql'
# namespaces asked about per request
BATCH = 40
OFFERS = '''{alias}: searchStore(namespace: "{namespace}", country: $country, locale: $locale, count: 100) {{
  elements {{ title offerType price(country: $country) {{
    totalPrice {{ originalPrice discountPrice currencyCode currencyInfo {{ decimals }} }} }} }}
}}'''


def store_offers(namespaces, country, locale):
    """The store's offers of each namespace, as (title, offer type, full price, today's price, currency, decimals)"""
    offers = {}
    namespaces = sorted(namespaces)
    for start in range(0, len(namespaces), BATCH):
        batch = namespaces[start:start + BATCH]
        # namespaces are hex ids from Epic; anything else is left out rather than put into the query
        batch = [namespace for namespace in batch if namespace.isalnum()]
        searches = '\n'.join(OFFERS.format(alias=f'n{index}', namespace=namespace)
                             for index, namespace in enumerate(batch))
        query = f'query($country: String!, $locale: String) {{ Catalog {{ {searches} }} }}'
        response = requests.post(STORE_API, json={'query': query, 'variables': {'country': country, 'locale': locale}},
                                 headers={'User-Agent': 'Heirloom'}, timeout=30)
        response.raise_for_status()
        catalog = (response.json().get('data') or {}).get('Catalog') or {}
        for index, namespace in enumerate(batch):
            offers[namespace] = [
                (element['title'], element['offerType'], price['originalPrice'], price['discountPrice'],
                 price['currencyCode'], price['currencyInfo']['decimals'])
                for element in ((catalog.get(f'n{index}') or {}).get('elements') or [])
                if element.get('price') and (price := element['price']['totalPrice'])]
    return offers


def price_library(games, offers):
    """
    games are (title, namespace, is DLC). Returns the priced ones as (title, full price, today's price), the titles
    not sold anymore, and the currency with its decimals.
    """
    priced, unpriced, currency = [], [], None
    for title, namespace, is_dlc in games:
        candidates = offers.get(namespace, [])
        if is_dlc:
            match = next((offer for offer in candidates if offer[0].casefold() == title.casefold()), None)
        else:
            match = next((offer for offer in candidates if offer[1] == 'BASE_GAME'), None)
        if match is None:
            unpriced.append(title)
            continue
        priced.append((title, match[2], match[3]))
        currency = currency or (match[4], match[5])
    return priced, unpriced, currency


def money(amount, currency):
    code, decimals = currency
    return f'{amount / 10 ** decimals:,.{decimals}f} {code}'


def setup(plugin):
    def worth(args, core):
        games = [game for game in map(core.lgd.get_game_meta, core.lgd.get_game_app_names())
                 if game and game.namespace]
        if not games:
            print('Your library is not loaded yet: open the window or run "heirloom list" first.')
            return
        print(f'Looking up the prices of {len(games)} games and DLC...')
        try:
            offers = store_offers({game.namespace for game in games}, core.country_code, core.language_code)
        except (requests.RequestException, ValueError, KeyError) as e:
            plugin.log.error(f'Could not get prices from the Epic Games Store: {e!r}')
            return
        priced, unpriced, currency = price_library(
            [(game.app_title, game.namespace, game.is_dlc) for game in games], offers)
        if not currency:
            print('None of your games is sold on the Epic Games Store in your country.')
            return
        full, today = sum(item[1] for item in priced), sum(item[2] for item in priced)
        print(f'Your library: {len(priced)} games and DLC with a price')
        print(f'  Worth at full price:      {money(full, currency)}')
        print(f"  Worth at today's prices:  {money(today, currency)}")
        if args.top:
            print('  Most valuable:')
            for title, original, _ in sorted(priced, key=lambda item: -item[1])[:args.top]:
                print(f'    {money(original, currency):>14}  {title}')
        if unpriced:
            print(f'  Not sold on the store anymore, or not in your country: {len(unpriced)} '
                  f'({", ".join(sorted(unpriced)[:5])}{", ..." if len(unpriced) > 5 else ""})')
        if args.json:
            print(json.dumps({'full_price': full, 'today': today, 'currency': currency[0], 'decimals': currency[1],
                              'priced': len(priced), 'unpriced': unpriced}))

    parser = plugin.command('worth', worth, help='What your library costs on the Epic Games Store')
    parser.add_argument('--top', type=int, default=5, metavar='<n>', help='List the n most valuable (default 5)')
    parser.add_argument('--json', action='store_true', help='Also print the totals as JSON')
