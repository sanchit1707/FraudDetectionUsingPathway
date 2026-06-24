import pathway as pw

class WatchlistSchema(pw.Schema):
    merchant_id: str
    risk_reason: str

def get_watchlist() -> pw.Table:
    """
    Loads the Slowly Changing Dimension (SCD) table of blocked merchants.
    """
    return pw.io.csv.read(
        "data/watchlist.csv",
        schema=WatchlistSchema,  
        mode="static"
    )
