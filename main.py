import asyncio
import json
import websockets
import requests
import aiohttp
from asyncio import Queue

order_queue = Queue()



# Configuration
WS_URL = 'ws://exchange-ws.figgiewars.com'
REST_URL = 'http://exchange.figgiewars.com'
PLAYER_ID = ''  # Replace with your player ID
PLAYER_NAME = '' # replace with your player name (seen on players page)

# State
awaiting_lock = {'heart': False, 'spade': False, 'diamond': False, 'club': False}
inventory = {'heart': 0, 'spade': 0, 'diamond': 0, 'club': 0}
order_book  = {
    'heart': {'bids': [], 'asks': [], 'last_trade': 0, 'volume': 0}, 
    'spade': {'bids': [], 'asks': [], 'last_trade': 0, 'volume': 0}, 
    'diamond': {'bids': [], 'asks': [], 'last_trade': 0, 'volume': 0}, 
    'club': {'bids': [], 'asks': [], 'last_trade': 0, 'volume': 0}
}
highest_card = None
assumed_goal_suit = None


async def get_inventory():
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{REST_URL}/inventory", headers={"Content-Type": "application/json", "playerid": PLAYER_ID}) as response:
            return await response.json()

async def send_init_message(websocket):
    message = {
        'action': "subscribe",
        'playerid': PLAYER_ID,
    }
    await websocket.send(json.dumps(message))

async def handle_message(message):
    global inventory, order_book, highest_card, assumed_goal_suit, PLAYER_ID, awaiting_lock

    if "kind" not in message:
        return
    
    if message['kind'] == "dealing_cards":
        # game has started, let's set out inventory and then place some initial spreads
        inventory['spade'] = message['data']['spades']
        inventory['club'] = message['data']['clubs']
        inventory['heart'] = message['data']['hearts']
        inventory['diamond'] = message['data']['diamonds']

        # which card is the highest?
        highest_card = max(inventory, key=inventory.get)
        # get the suit of the same color as the highest card
        if highest_card == "heart":
            assumed_goal_suit = "diamond"
        elif highest_card == "diamond":
            assumed_goal_suit = "heart"
        elif highest_card == "spade":
            assumed_goal_suit = "club"
        elif highest_card == "club":
            assumed_goal_suit = "spade"

    elif message['kind'] == "update":
        # let's parse some updates
        print("Getting update: ", message['data'])

        order_book['spade']['bids'] = message['data']['spades']['bids']
        order_book['spade']['asks'] = message['data']['spades']['asks']

        order_book['club']['bids'] = message['data']['clubs']['bids']
        order_book['club']['asks'] = message['data']['clubs']['asks']

        order_book['heart']['bids'] = message['data']['hearts']['bids']
        order_book['heart']['asks'] = message['data']['hearts']['asks']

        order_book['diamond']['bids'] = message['data']['diamonds']['bids']
        order_book['diamond']['asks'] = message['data']['diamonds']['asks']


        if message['data']['trade'] != "":
            card, price, buyer, seller = message['data']['trade'].split(',')

            if card == "spade":
                if buyer == PLAYER_NAME:
                    inventory['spade'] += 1
                elif seller == PLAYER_NAME:
                    inventory['spade'] -= 1
                order_book['spade']['last_trade'] = price
                order_book['spade']['volume'] += 1
            elif card == "club":
                if buyer == PLAYER_NAME:
                    inventory['club'] += 1
                elif seller == PLAYER_NAME:
                    inventory['club'] -= 1
                order_book['club']['last_trade'] = price
                order_book['club']['volume'] += 1
            elif card == "heart":
                if buyer == PLAYER_NAME:
                    inventory['heart'] += 1
                elif seller == PLAYER_NAME:
                    inventory['heart'] -= 1
                order_book['heart']['last_trade'] = price
                order_book['heart']['volume'] += 1
            elif card == "diamond":
                if buyer == PLAYER_NAME:
                    inventory['diamond'] += 1
                elif seller == PLAYER_NAME:
                    inventory['diamond'] -= 1
                order_book['diamond']['last_trade'] = price
                order_book['diamond']['volume'] += 1


        if assumed_goal_suit == None:
            got_inventory = await get_inventory()
            got_inventory_json = json.loads(got_inventory)
            split_cards = got_inventory_json['message'].split(',')

            inventory['spade'] = int(split_cards[0])
            inventory['club'] = int(split_cards[1])
            inventory['diamond'] = int(split_cards[2])
            inventory['heart'] = int(split_cards[3])
            
            highest_card = max(inventory, key=inventory.get)
            if highest_card == "heart":
                assumed_goal_suit = "diamond"
            elif highest_card == "diamond":
                assumed_goal_suit = "heart"
            elif highest_card == "spade":
                assumed_goal_suit = "club"
            elif highest_card == "club":
                assumed_goal_suit = "spade"

        # let's place some orders

        card_with_highest_volume = max(order_book, key=lambda x: order_book[x]['volume'])
        if card_with_highest_volume == "heart":
            highest_vol_flip = "diamond"
        elif card_with_highest_volume == "diamond":
            highest_vol_flip = "heart"
        elif card_with_highest_volume == "spade":
            highest_vol_flip = "club"
        elif card_with_highest_volume == "club":
            highest_vol_flip = "spade"


        # THIS LED TO A COMPLETE LOSS (4TH PLACE) IN SILVER, USE AS EXAMPLE OF WHAT NOT TO DO (I GUESS)
        for card in inventory:
            if inventory[card] > 0 and card != assumed_goal_suit:
                if order_book[card]['asks']:
                    best_ask = min(order_book[card]['asks'], key=lambda x: x[0])
                    if best_ask[0] > 7:
                        await order_queue.put((card, best_ask[0] - 1, "sell"))
                else:
                    await order_queue.put((card, 13, "sell"))

                if order_book[card]['bids']:
                    best_bid = max(order_book[card]['bids'], key=lambda x: x[0])
                    if best_bid[0] <= 1:
                        await order_queue.put((card, best_bid[0] + 1, "buy"))
                else:
                    await order_queue.put((card, 1, "buy"))
            if card == assumed_goal_suit:
                if order_book[card]['bids']:
                    best_bid = max(order_book[card]['bids'], key=lambda x: x[0])
                    if best_bid[0] < 3:
                        await order_queue.put((card, best_bid[0] + 1, "buy"))
                else:
                    await order_queue.put((card, 1, "buy"))
            if card == highest_vol_flip:
                if order_book[card]['bids']:
                    best_bid = max(order_book[card]['bids'], key=lambda x: x[0])
                    if best_bid[0] < 5:
                        await order_queue.put((card, best_bid[0] + 1, "buy"))
                else:
                    await order_queue.put((card, 1, "buy"))
            if inventory[card] == 0:
                if order_book[card]['asks']:
                    best_ask = max(order_book[card]['asks'], key=lambda x: x[0])
                    if best_ask[0] <= 2:
                        await order_queue.put((card, best_ask[0], "buy"))


    elif message['kind'] == "end_round":
        # end of round
        print("End of round")
    elif message['kind'] == "end_game":
        # end of game 
        print("End of game")

async def websocket_listener():
    while True:
        try:
            async with websockets.connect(f"{WS_URL}") as websocket:
                await send_init_message(websocket)
                
                while True:
                    try:
                        # Use wait_for with a short timeout to make it non-blocking
                        message = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                        data = json.loads(message)
                        await handle_message(data)
                    except asyncio.TimeoutError:
                        # No new message, continue to next iteration
                        continue
        except websockets.exceptions.ConnectionClosed:
            print("WebSocket connection closed. Reconnecting...")
        except Exception as e:
            print(f"Error in WebSocket connection: {e}")
        await asyncio.sleep(5)  # Wait before reconnecting

async def place_order(card, price, direction: str):
    print(f"[+] Placing order |:| Card: {card} | Price: {price} | Direction: {direction}")
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{REST_URL}/order", json={
            'card': card,
            'price': price,
            'direction': direction
        }, headers={"Content-Type": "application/json", "playerid": PLAYER_ID}) as response:
            return await response.json()


async def process_orders():
    while True:
        card, price, direction = await order_queue.get()
        try:
            await place_order(card, price, direction)
        except Exception as e:
            print(f"Error placing order: {e}")
        finally:
            order_queue.task_done()


async def main():
    listener_task = asyncio.create_task(websocket_listener())
    order_processor_task = asyncio.create_task(process_orders())
    
    await asyncio.gather(listener_task, order_processor_task)

if __name__ == "__main__":
    asyncio.run(main())

