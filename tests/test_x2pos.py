import asyncio
import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch, MagicMock, AsyncMock
from urllib.error import HTTPError
from x2pos import client, handlers

ENV={"X2POS_API_KEY":"secret","X2POS_OWNER_ID":"123","X2POS_BRANCH_ID":"7","X2POS_USER_ID":"8"}
EMP={"branches":["7"],"user_id":"8","key":"secret","email":"private"}
PRODUCT=[{"product_name":"Товар","variations":[{"id":"10","retail_price":"100","wholesale_price":"90","measurement_unit":"unit_piece"}]}]

class Tests(unittest.TestCase):
    def test_request_header_and_get(self):
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b"[]"
        with patch.dict("os.environ",ENV),patch.object(client,"build_opener") as build:
            build.return_value.open.return_value=response
            client.request("/products",{"page":1})
            req=build.return_value.open.call_args.args[0]
            self.assertEqual(req.get_method(),"GET")
            self.assertEqual(req.get_header("Api-key"),"secret")
            self.assertEqual(req.full_url,"https://x2pos.com/api/products?page=1")
            self.assertEqual(build.return_value.open.call_args.kwargs["timeout"],10)

    def test_redirect_and_endpoint(self):
        self.assertIsNone(client.NoRedirect().redirect_request(None,None,302,"",{},"https://evil.invalid"))
        with self.assertRaises(ValueError):
            client.request("/orders")

    def test_missing_key_no_network(self):
        with patch.dict("os.environ",{"X2POS_API_KEY":""}),patch.object(client,"build_opener") as build:
            with self.assertRaises(client.X2Error):
                client.request("/products")
            build.assert_not_called()

    def test_error_never_exposes_key_or_body(self):
        with patch.dict("os.environ",ENV),patch.object(client,"build_opener") as build:
            build.return_value.open.side_effect=HTTPError("secret",403,"private",{},None)
            with self.assertRaises(client.X2Error) as e:
                client.request("/employee")
            self.assertNotIn("secret",str(e.exception))
            self.assertNotIn("private",str(e.exception))

    def test_branch_access_before_products(self):
        with patch.dict("os.environ",ENV),patch.object(client,"request",return_value={**EMP,"branches":["9"]}) as request:
            with self.assertRaises(client.X2Error):
                client.catalog(1)
            self.assertEqual(request.call_count,1)

    def test_stock_matches_variation_and_missing_not_zero(self):
        def request(path,*args):
            return {"/employee":EMP,"/products":PRODUCT,"/stock":{}}[path]
        with patch.dict("os.environ",ENV),patch.object(client,"request",side_effect=request):
            rows=client.catalog(1)
            self.assertEqual(rows[0]["quantity"],"нет данных")
            self.assertEqual(rows[0]["id"],"10")
            self.assertNotIn("key",rows[0])

    def test_foreign_stock_rejected(self):
        with patch.object(client,"request",return_value={"10":{"variation_id":10,"branch_id":9,"quantity":1}}):
            with self.assertRaises(client.X2Error):
                client.stock("7")

    def test_variation_dictionary(self):
        data=[{**PRODUCT[0],"variations":{"10":PRODUCT[0]["variations"][0]}}]
        with patch.object(client,"request",return_value=data):
            self.assertEqual(client.products(1)[0]["id"],"10")
        with patch.object(client,"request",return_value=[{**PRODUCT[0],"variations":"bad"}]):
            with self.assertRaises(client.X2Error):
                client.products(1)

    def test_nonfinite_number_and_schema(self):
        for value in ("NaN","Infinity","invalid"):
            with self.assertRaises(client.X2Error):
                client.number(value)
        with patch.object(client,"request",return_value={"error":"private"}):
            with self.assertRaises(client.X2Error):
                client.products()

    def test_movement_headers_and_filter(self):
        doc={"id":"33","branch_id":"7","action":"acceptance","total_quantity":2,"total_amount":100,"notes":"private"}
        with patch.dict("os.environ",ENV),patch.object(client,"request",side_effect=[EMP,{"status":"success","procurements":[doc]}]) as request:
            rows=client.movements("acceptance",1)
            self.assertNotIn("notes",rows[0])
            self.assertEqual(request.call_args.args[2],{"User-Id":"8","Branch-Id":"7"})
        with patch.dict("os.environ",ENV),patch.object(client,"request",side_effect=[EMP,{"status":"success","procurements":[{**doc,"branch_id":"9"}]}]):
            with self.assertRaises(client.X2Error):
                client.movements("acceptance",1)

    def test_unauthorized_never_requests(self):
        for owner,chat in ((999,"private"),(123,"group")):
            q=NS(answer=AsyncMock(),message=NS(reply_text=AsyncMock()),data="x2pos:check")
            update=NS(effective_user=NS(id=owner),effective_chat=NS(id=owner,type=chat),callback_query=q)
            with patch.dict("os.environ",ENV),patch.object(client,"employee") as request:
                asyncio.run(handlers.callback(update,NS(user_data={})))
                request.assert_not_called()
                q.message.reply_text.assert_not_called()

if __name__=="__main__":
    unittest.main()
