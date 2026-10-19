def demo_documents(variant="conflict", index=0):
    qty, price = 5000 + index * 10, 18
    common = f"Seller: Ningbo Horizon Goods Co Ltd\nBuyer: Northstar Trading Ltd\nCurrency: USD\nQuantity: {qty}\n"
    quote = common + f"Total: USD {qty*price}\nDeposit: 30%\nBalance due: 30 days\nPayment trigger: bill of lading copy\nShipment date: 2027-01-15\nIncoterm: FOB Ningbo Incoterms 2020\n"
    inquiry = f"Buyer: Northstar Trading Ltd\nQuantity: {qty}\nShipment date: 2027-01-15\nPlease quote household storage products.\n"
    total, deposit, days = (qty * price + 5000, 0, 90) if variant == "conflict" else (qty * price, 30, 30)
    contract = common + f"Total: USD {total}\nDeposit: {deposit}%\nBalance due: {days} days\nPayment trigger: bill of lading copy\nShipment date: 2027-01-15\nIncoterm: FOB Ningbo Incoterms 2020\nInspection: Written objections within 15 days after delivery\nLiability: Parties shall negotiate an agreed cap before signing\nDispute resolution: Institution and seat to be confirmed\n"
    if variant == "missing":
        contract = "Seller: Ningbo Horizon Goods Co Ltd\nQuantity: 5000\nPayment: To be agreed\n"
    return [("inquiry", "inquiry.txt", inquiry), ("quote", "quotation.txt", quote), ("contract", "contract.txt", contract)]
