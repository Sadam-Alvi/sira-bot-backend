from fastapi import FastAPI, Request, HTTPException
from typing import Any, Dict
import pandas as pd
import re
import os
import uvicorn
from threading import Lock


# ============================================================
# CSV FILES
# ============================================================

FOOD_ITEMS_FILE = "db/food_items.csv"
ORDERS_FILE = "db/orders.csv"

# Prevent two requests from modifying the CSV at the same time
csv_lock = Lock()


# ============================================================
# CSV INITIALIZATION
# ============================================================

def initialize_csv_files():

    # -------------------------
    # food_items.csv
    # -------------------------
    if not os.path.exists(FOOD_ITEMS_FILE):

        food_items = pd.DataFrame([
            [1, "Burger", 300],
            [2, "Pizza", 500],
            [3, "Pasta", 400],
            [4, "Fried Chicken", 350],
            [5, "Sandwich", 250],
            [6, "Biryani", 350]
        ], columns=[
            "item_id",
            "name",
            "price"
        ])

        food_items.to_csv(
            FOOD_ITEMS_FILE,
            index=False
        )

    # -------------------------
    # orders.csv
    # -------------------------
    if not os.path.exists(ORDERS_FILE):

        orders = pd.DataFrame(columns=[
            "order_row_id",
            "order_id",
            "item_id",
            "quantity",
            "status",
            "total_price"
        ])

        orders.to_csv(
            ORDERS_FILE,
            index=False
        )


initialize_csv_files()


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Dialogflow Webhook"
)


# ============================================================
# SESSION STORAGE
# ============================================================

last_orders = {}


# ============================================================
# CSV HELPERS
# ============================================================

def load_food_items():

    return pd.read_csv(
        FOOD_ITEMS_FILE
    )


def load_orders():

    return pd.read_csv(
        ORDERS_FILE
    )


def save_orders(df):

    df.to_csv(
        ORDERS_FILE,
        index=False
    )


# ============================================================
# DIALOGFLOW REQUEST EXTRACTION
# ============================================================

def extract_from_request(
    body: Dict[str, Any]
):

    session = body.get(
        "session",
        ""
    )

    # Example:
    # projects/PROJECT_ID/agent/sessions/SESSION_ID

    session_id = (
        session.split("/")[-1]
        if session
        else "unknown"
    )

    query_result = body.get(
        "queryResult",
        {}
    )

    intent_name = query_result.get(
        "intent",
        {}
    ).get(
        "displayName",
        ""
    )

    parameters = query_result.get(
        "parameters",
        {}
    ) or {}

    return (
        session_id,
        intent_name,
        parameters
    )


# ============================================================
# COMMON DIALOGFLOW RESPONSE
# ============================================================

def dialogflow_response(message):

    return {
        "fulfillmentText": message,
        "fulfillmentMessages": [
            {
                "text": {
                    "text": [message]
                }
            }
        ]
    }


# ============================================================
# PLACE ORDER
# ============================================================

def order_place(
    session_id: str,
    parameters: Dict[str, Any]
):

    try:

        # -------------------------
        # Get values from Dialogflow
        # -------------------------

        food_items = parameters.get(
            "food-item"
        )

        quantities = parameters.get(
            "number"
        )

        if not food_items or not quantities:

            return dialogflow_response(
                "Please provide the food items and quantities."
            )

        # Dialogflow may return one value
        # instead of a list

        if not isinstance(
            food_items,
            list
        ):

            food_items = [
                food_items
            ]

        if not isinstance(
            quantities,
            list
        ):

            quantities = [
                quantities
            ]

        # -------------------------
        # Match food and quantity
        # -------------------------

        if len(food_items) != len(
            quantities
        ):

            return dialogflow_response(
                "I couldn't match the quantities with the food items."
            )

        # ====================================================
        # LOCK CSV
        # ====================================================

        with csv_lock:

            # -------------------------
            # Load CSV files
            # -------------------------

            food_df = load_food_items()

            orders_df = load_orders()

            # -------------------------
            # Make sure numeric columns
            # are numeric
            # -------------------------

            if not orders_df.empty:

                orders_df[
                    "order_row_id"
                ] = pd.to_numeric(
                    orders_df[
                        "order_row_id"
                    ],
                    errors="coerce"
                )

                orders_df[
                    "order_id"
                ] = pd.to_numeric(
                    orders_df[
                        "order_id"
                    ],
                    errors="coerce"
                )

                orders_df[
                    "item_id"
                ] = pd.to_numeric(
                    orders_df[
                        "item_id"
                    ],
                    errors="coerce"
                )

                orders_df[
                    "quantity"
                ] = pd.to_numeric(
                    orders_df[
                        "quantity"
                    ],
                    errors="coerce"
                )

                orders_df[
                    "total_price"
                ] = pd.to_numeric(
                    orders_df[
                        "total_price"
                    ],
                    errors="coerce"
                )

            # ====================================================
            # GET EXISTING ORDER ID
            # ====================================================

            if session_id in last_orders:

                order_id = last_orders[
                    session_id
                ][
                    "order_id"
                ]

                # Check if order still exists

                existing_order = orders_df[
                    orders_df[
                        "order_id"
                    ] == order_id
                ]

                if existing_order.empty:

                    del last_orders[
                        session_id
                    ]

            # ====================================================
            # CREATE NEW ORDER ID
            # ====================================================

            if session_id not in last_orders:

                if orders_df.empty:

                    order_id = 1

                else:

                    max_order_id = pd.to_numeric(
                        orders_df[
                            "order_id"
                        ],
                        errors="coerce"
                    ).max()

                    if pd.isna(
                        max_order_id
                    ):

                        max_order_id = 0

                    order_id = int(
                        max_order_id
                    ) + 1

                last_orders[
                    session_id
                ] = {
                    "order_id": order_id,
                    "total_price": 0
                }

            else:

                order_id = last_orders[
                    session_id
                ][
                    "order_id"
                ]

            # ====================================================
            # PROCESS ITEMS
            # ====================================================

            ordered_items = []

            for food_item, quantity in zip(
                food_items,
                quantities
            ):

                # -------------------------
                # Clean food name
                # -------------------------

                food_item = re.sub(
                    r"[^\w\s]",
                    "",
                    str(food_item)
                )

                food_item = " ".join(
                    food_item.split()
                ).strip()

                quantity = int(
                    quantity
                )

                if quantity <= 0:

                    raise ValueError(
                        "Quantity must be greater than zero."
                    )

                print(
                    "Food:",
                    food_item
                )

                print(
                    "Quantity:",
                    quantity
                )

                # ====================================================
                # FIND FOOD ITEM
                # ====================================================

                food_match = food_df[
                    food_df[
                        "name"
                    ].astype(str).str.strip().str.lower()
                    ==
                    food_item.strip().lower()
                ]

                if food_match.empty:

                    return dialogflow_response(
                        f"Sorry, {food_item} is not available on the menu."
                    )

                food = food_match.iloc[0]

                item_id = int(
                    food["item_id"]
                )

                food_name = str(
                    food["name"]
                )

                price = float(
                    food["price"]
                )

                # ====================================================
                # CHECK IF ITEM ALREADY EXISTS
                # ====================================================

                existing_item = orders_df[
                    (orders_df[
                        "order_id"
                    ] == order_id)
                    &
                    (orders_df[
                        "item_id"
                    ] == item_id)
                ]

                if not existing_item.empty:

                    # -------------------------
                    # Existing item
                    # -------------------------

                    row_index = (
                        existing_item.index[0]
                    )

                    old_quantity = int(
                        orders_df.loc[
                            row_index,
                            "quantity"
                        ]
                    )

                    new_quantity = (
                        old_quantity
                        + quantity
                    )

                    orders_df.loc[
                        row_index,
                        "quantity"
                    ] = new_quantity

                    orders_df.loc[
                        row_index,
                        "status"
                    ] = "in transit"

                else:

                    # -------------------------
                    # New item
                    # -------------------------

                    if orders_df.empty:

                        order_row_id = 1

                    else:

                        max_row_id = pd.to_numeric(
                            orders_df[
                                "order_row_id"
                            ],
                            errors="coerce"
                        ).max()

                        if pd.isna(
                            max_row_id
                        ):

                            max_row_id = 0

                        order_row_id = int(
                            max_row_id
                        ) + 1

                    new_row = pd.DataFrame([
                        {
                            "order_row_id": order_row_id,
                            "order_id": order_id,
                            "item_id": item_id,
                            "quantity": quantity,
                            "status": "in transit",
                            "total_price": price * quantity
                        }
                    ])

                    orders_df = pd.concat(
                        [
                            orders_df,
                            new_row
                        ],
                        ignore_index=True
                    )

                ordered_items.append(
                    f"{quantity} {food_name}"
                )

            # ====================================================
            # CALCULATE COMPLETE ORDER TOTAL
            # ====================================================

            current_order = orders_df[
                orders_df[
                    "order_id"
                ] == order_id
            ]

            total_price = 0.0

            for _, row in current_order.iterrows():

                item_id = int(
                    row["item_id"]
                )

                quantity = int(
                    row["quantity"]
                )

                food_match = food_df[
                    food_df[
                        "item_id"
                    ] == item_id
                ]

                if not food_match.empty:

                    price = float(
                        food_match.iloc[0][
                            "price"
                        ]
                    )

                    total_price += (
                        price * quantity
                    )

            # ====================================================
            # UPDATE TOTAL PRICE
            # ====================================================

            orders_df.loc[
                orders_df[
                    "order_id"
                ] == order_id,
                "total_price"
            ] = total_price

            # ====================================================
            # SAVE CSV
            # ====================================================

            save_orders(
                orders_df
            )

            # ====================================================
            # SAVE SESSION
            # ====================================================

            last_orders[
                session_id
            ] = {
                "order_id": order_id,
                "total_price": total_price
            }

        # ====================================================
        # RESPONSE
        # ====================================================

        item_text = ", ".join(
            ordered_items
        )

        message = (
            f"Your order has been placed successfully! "
            f"You ordered {item_text}. "
            f"Order ID: #{order_id}. "
            f"Total price: {total_price:.2f}. "
            f"Anything else?"
        )

        return dialogflow_response(
            message
        )

    except ValueError as e:

        print(
            "ORDER INPUT ERROR:",
            repr(e)
        )

        return dialogflow_response(
            str(e)
        )

    except Exception as e:

        print(
            "ORDER ERROR:",
            repr(e)
        )

        return dialogflow_response(
            f"Order error: {str(e)}"
        )


# ============================================================
# CANCEL COMPLETE ORDER
# ============================================================

def order_remove(
    session_id: str,
    parameters: Dict[str, Any]
):

    order_id = (
        parameters.get("order_id")
        or parameters.get("orderId")
        or parameters.get("number")
    )

    # Dialogflow may return a list

    if isinstance(
        order_id,
        list
    ):

        order_id = (
            order_id[0]
            if order_id
            else None
        )

    if not order_id:

        return dialogflow_response(
            "Please provide your Order ID so I can cancel your order."
        )

    try:

        order_id = int(
            order_id
        )

        with csv_lock:

            orders_df = load_orders()

            # -------------------------
            # Check order
            # -------------------------

            existing_order = orders_df[
                orders_df[
                    "order_id"
                ] == order_id
            ]

            if existing_order.empty:

                return dialogflow_response(
                    f"I couldn't find an order with ID #{order_id}."
                )

            # -------------------------
            # Delete order
            # -------------------------

            orders_df = orders_df[
                orders_df[
                    "order_id"
                ] != order_id
            ]

            # -------------------------
            # Save CSV
            # -------------------------

            save_orders(
                orders_df
            )

            # Remove session

            sessions_to_remove = []

            for session, data in last_orders.items():

                if data[
                    "order_id"
                ] == order_id:

                    sessions_to_remove.append(
                        session
                    )

            for session in sessions_to_remove:

                last_orders.pop(
                    session,
                    None
                )

        message = (
            f"Your order #{order_id} "
            f"has been cancelled successfully."
        )

        return dialogflow_response(
            message
        )

    except ValueError:

        return dialogflow_response(
            "Please provide a valid numeric Order ID."
        )

    except Exception as e:

        print(
            "Cancel order error:",
            repr(e)
        )

        return dialogflow_response(
            "Sorry, I couldn't cancel your order right now."
        )


# ============================================================
# TRACK ORDER
# ============================================================

def order_track(
    session_id: str,
    parameters: Dict[str, Any]
):

    order_id = (
        parameters.get("order_id")
        or parameters.get("orderId")
        or parameters.get("number")
    )

    if isinstance(
        order_id,
        list
    ):

        order_id = (
            order_id[0]
            if order_id
            else None
        )

    if not order_id:

        return dialogflow_response(
            "Please provide your Order ID so I can track it."
        )

    try:

        order_id = int(
            order_id
        )

        orders_df = load_orders()

        results = orders_df[
            orders_df[
                "order_id"
            ] == order_id
        ]

        if results.empty:

            message = (
                f"I couldn't find an order with ID #{order_id}."
            )

        else:

            status = str(
                results.iloc[0][
                    "status"
                ]
            )

            message = (
                f"Your order #{order_id} "
                f"is currently {status}."
            )

        return dialogflow_response(
            message
        )

    except ValueError:

        return dialogflow_response(
            "Please provide a valid numeric Order ID."
        )

    except Exception as e:

        print(
            "Track order error:",
            repr(e)
        )

        return dialogflow_response(
            "Sorry, I couldn't check your order status right now."
        )


# ============================================================
# GET ORDER TOTAL
# ============================================================

def get_order_total(
    session_id: str
):

    try:

        if session_id not in last_orders:

            return 0.0, ""

        order_id = last_orders[
            session_id
        ][
            "order_id"
        ]

        food_df = load_food_items()

        orders_df = load_orders()

        current_order = orders_df[
            orders_df[
                "order_id"
            ] == order_id
        ]

        total_charges = 0.0

        ordered_items = []

        for _, row in current_order.iterrows():

            item_id = int(
                row["item_id"]
            )

            quantity = int(
                row["quantity"]
            )

            food_match = food_df[
                food_df[
                    "item_id"
                ] == item_id
            ]

            if food_match.empty:

                continue

            food = food_match.iloc[0]

            name = str(
                food["name"]
            )

            price = float(
                food["price"]
            )

            total_charges += (
                price * quantity
            )

            ordered_items.append(
                f"{quantity} {name}"
            )

        names = ", ".join(
            ordered_items
        )

        return (
            total_charges,
            names
        )

    except Exception as e:

        print(
            "Get order total error:",
            repr(e)
        )

        return 0.0, ""


# ============================================================
# REMOVE ITEM FROM CURRENT ORDER
# ============================================================

def item_remove(
    session_id: str,
    parameters: Dict[str, Any]
):

    try:

        # ====================================================
        # CHECK ACTIVE ORDER
        # ====================================================

        if session_id not in last_orders:

            return dialogflow_response(
                "You don't have an active order."
            )

        order_id = last_orders[
            session_id
        ][
            "order_id"
        ]

        # ====================================================
        # GET FOOD ITEM
        # ====================================================

        food_item = (
            parameters.get("food-item")
            or parameters.get("food_item")
            or parameters.get("item")
        )

        if isinstance(
            food_item,
            list
        ):

            food_item = (
                food_item[0]
                if food_item
                else None
            )

        if not food_item:

            return dialogflow_response(
                "Please tell me which food item you want to remove."
            )

        # ====================================================
        # CLEAN FOOD NAME
        # ====================================================

        food_item = re.sub(
            r"[^\w\s]",
            "",
            str(food_item)
        )

        food_item = " ".join(
            food_item.split()
        ).strip()

        with csv_lock:

            food_df = load_food_items()

            orders_df = load_orders()

            # ====================================================
            # FIND FOOD
            # ====================================================

            food_match = food_df[
                food_df[
                    "name"
                ].astype(str).str.strip().str.lower()
                ==
                food_item.strip().lower()
            ]

            if food_match.empty:

                return dialogflow_response(
                    f"Sorry, {food_item} is not available on the menu."
                )

            food = food_match.iloc[0]

            item_id = int(
                food["item_id"]
            )

            food_name = str(
                food["name"]
            )

            # ====================================================
            # CHECK ITEM IN ORDER
            # ====================================================

            existing_item = orders_df[
                (orders_df[
                    "order_id"
                ] == order_id)
                &
                (orders_df[
                    "item_id"
                ] == item_id)
            ]

            if existing_item.empty:

                return dialogflow_response(
                    f"{food_name} is not in your current order."
                )

            # ====================================================
            # REMOVE ITEM
            # ====================================================

            orders_df = orders_df[
                ~(
                    (orders_df[
                        "order_id"
                    ] == order_id)
                    &
                    (orders_df[
                        "item_id"
                    ] == item_id)
                )
            ]

            # ====================================================
            # CHECK REMAINING ITEMS
            # ====================================================

            remaining = orders_df[
                orders_df[
                    "order_id"
                ] == order_id
            ]

            if remaining.empty:

                save_orders(
                    orders_df
                )

                last_orders.pop(
                    session_id,
                    None
                )

                return dialogflow_response(
                    f"{food_name} has been removed. "
                    f"Your order is now empty."
                )

            # ====================================================
            # RECALCULATE TOTAL
            # ====================================================

            total_charges = 0.0

            for _, row in remaining.iterrows():

                remaining_item_id = int(
                    row["item_id"]
                )

                quantity = int(
                    row["quantity"]
                )

                food_match = food_df[
                    food_df[
                        "item_id"
                    ] == remaining_item_id
                ]

                if not food_match.empty:

                    price = float(
                        food_match.iloc[0][
                            "price"
                        ]
                    )

                    total_charges += (
                        price * quantity
                    )

            # ====================================================
            # UPDATE TOTAL
            # ====================================================

            orders_df.loc[
                orders_df[
                    "order_id"
                ] == order_id,
                "total_price"
            ] = total_charges

            # ====================================================
            # SAVE CSV
            # ====================================================

            save_orders(
                orders_df
            )

            # ====================================================
            # UPDATE SESSION
            # ====================================================

            last_orders[
                session_id
            ][
                "total_price"
            ] = total_charges

        # ====================================================
        # RESPONSE
        # ====================================================

        message = (
            f"{food_name} has been removed "
            f"from your order. "
            f"Your new total is "
            f"Rs. {total_charges:.2f}. "
            f"Anything else?"
        )

        return dialogflow_response(
            message
        )

    except Exception as e:

        print(
            "Remove item error:",
            repr(e)
        )

        return dialogflow_response(
            "Sorry, I couldn't remove that item."
        )


# ============================================================
# MAIN WEBHOOK
# ============================================================

@app.post("/webhook")
async def dialogflow_webhook(
    request: Request
):

    try:

        body = await request.json()

    except Exception:

        raise HTTPException(
            status_code=400,
            detail="Invalid JSON body"
        )

    (
        session_id,
        intent_name,
        parameters
    ) = extract_from_request(
        body
    )

    print(
        f"Session: {session_id} | "
        f"Intent: {intent_name} | "
        f"Params: {parameters}"
    )

    # ========================================================
    # ROUTE INTENTS
    # ========================================================

    intent = intent_name.strip().lower()

    if intent == "add-order":

        response = order_place(
            session_id,
            parameters
        )

    elif intent == "cancel-order":

        response = order_remove(
            session_id,
            parameters
        )

    elif intent == "removing-item":

        response = item_remove(
            session_id,
            parameters
        )

    elif intent == "tracking-order-by-id":

        response = order_track(
            session_id,
            parameters
        )

    elif intent == "order-complete":

        total_charges, names = get_order_total(
            session_id
        )

        message = (
            f"Thanks Sir, your order has been placed! "
            f"Your final total charges are "
            f"You have ordered {names}. "
            f"Rs. {total_charges:.2f}."
        )

        response = dialogflow_response(
            message
        )

    else:

        response = dialogflow_response(
            "Sorry, I didn't understand that request."
        )

    return response


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
async def health():

    return {
        "status": "ok",
        "message": "Dialogflow webhook is running"
    }


# ============================================================
# RUN SERVER
# ============================================================

if __name__ == "__main__":

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )