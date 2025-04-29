from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import psycopg2
import os
from dotenv import load_dotenv
from datetime import timedelta
import datetime


load_dotenv()  # .env読み込み

app = Flask(__name__)
CORS(app)  # フロント連携用

# Neonの接続情報（.envで管理がおすすめ）
DATABASE_URL = os.getenv("DATABASE_URL")

def get_connection():
    return psycopg2.connect(DATABASE_URL)

@app.route("/")
def index():
    return render_template("inventory.html")  # とりあえず在庫一覧がトップでもOK

# 入荷予定一覧を取得
@app.route("/api/arrival_schedules", methods=["GET"])
def get_arrival_schedules():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id, m.name, s.quantity, s.arrival_date, s.comment
        FROM material_arrival_schedules s
        JOIN materials m ON s.material_id = m.id
        ORDER BY s.arrival_date, s.id
    """)
    result = [
        {
            "id": r[0],
            "material_name": r[1],
            "quantity": r[2],
            "arrival_date": r[3],
            "comment": r[4]
        }
        for r in cur.fetchall()
    ]
    cur.close()
    conn.close()
    return jsonify(result)


# 新しい入荷予定を登録
@app.route("/api/arrival_schedules", methods=["POST"])
def add_arrival_schedule():
    data = request.get_json()
    material_id = data["material_id"]
    quantity = data["quantity"]
    arrival_date = data.get("arrival_date")  # 任意
    comment = data.get("comment", "")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO material_arrival_schedules (material_id, quantity, arrival_date, comment)
        VALUES (%s, %s, %s, %s)
    """, (material_id, quantity, arrival_date, comment))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "入荷予定を追加しました"}), 201


# 入荷予定を削除（完了 or キャンセル）
@app.route("/api/arrival_schedules/<int:id>", methods=["DELETE"])
def delete_arrival_schedule(id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM material_arrival_schedules WHERE id = %s", (id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "入荷予定を削除しました"}), 200



# 作業予定インポート
@app.route("/api/shipments/register", methods=["POST"])
def register_shipments():
    data = request.json
    shipments = data.get("shipments", [])

    conn = get_connection()
    cur = conn.cursor()

    temp = {}

    for item in shipments:
        product_id = item.get("finished_id")
        if not product_id:
            continue

        pack = int(item.get("入数", 0) or 0)
        raw_jan = item.get("JANコード", "")
        if raw_jan is None:
            jan_code = ""
        else:
            raw_jan = str(raw_jan)
            if len(raw_jan) == 5:
                jan_code = "0" + raw_jan
            else:
                jan_code = raw_jan

        for day in ["月", "火", "水", "木", "金", "土", "日"]:
            raw_qty = item.get(day)
            try:
                qty = int(raw_qty) if raw_qty not in [None, ""] else 0
            except ValueError:
                qty = 0

            if qty <= 0:
                continue

            total_qty = pack * qty

            key = (product_id, day, jan_code)

            if key in temp:
                temp[key] += total_qty
            else:
                temp[key] = total_qty

    inserted = 0
    for (product_id, day, jan_code), total_qty in temp.items():
        comment = f"出荷予定インポート: {day}"
        cur.execute("""
            INSERT INTO work_schedules (product_type, product_id, quantity, comment, jan_code)
            VALUES ('finished', %s, %s, %s, %s)
        """, (product_id, total_qty, comment, jan_code))
        inserted += 1

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"message": f"{inserted} 件の作業予定を登録しました。"})



@app.route("/api/finished_products/lookup", methods=["POST"])
def lookup_finished_product():
    data = request.json
    name = data.get("product_name", "").strip()
    destination = data.get("destination", "").strip()
    size = data.get("size", "").strip()
    origin = data.get("origin", "").strip()

    conn = get_connection()
    cur = conn.cursor()

    # 完全一致（スペース・大小文字も無視）で探す
    cur.execute("""
        SELECT fp.id, m_label.name, m_bag.name
        FROM finished_products fp
        JOIN semi_products sp ON fp.semi_product_id = sp.id
        JOIN materials m_label ON sp.label_material_id = m_label.id
        JOIN materials m_bag ON sp.bag_material_id = m_bag.id
        WHERE LOWER(TRIM(fp.product_name)) = LOWER(%s)
          AND LOWER(TRIM(fp.destination)) = LOWER(%s)
          AND LOWER(TRIM(fp.size)) = LOWER(%s)
          AND LOWER(TRIM(fp.origin)) = LOWER(%s)
          AND fp.is_active = TRUE
        LIMIT 1;
    """, (name, destination, size, origin))


    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        return jsonify({
            "id": row[0],
            "name": f"{row[1]} + {row[2]}"  # 表シール + 袋
        })
    else:
        return jsonify({})




# 包材一覧取得（GET）
@app.route("/api/materials", methods=["GET"])
def get_materials():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, type, name, is_active, created_at FROM materials ORDER BY created_at;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{
        "id": r[0],
        "type": r[1],
        "name": r[2],
        "is_active": r[3],
        "created_at": r[4].strftime("%Y-%m-%d")  # ← ここで日付整形！
    } for r in rows])


# 包材追加（POST）
@app.route("/api/materials", methods=["POST"])
def add_material():
    data = request.json
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO materials (type, name) VALUES (%s, %s) RETURNING id;", (data["type"], data["name"]))
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201

@app.route("/api/materials/<int:material_id>/toggle", methods=["PATCH"])
def toggle_material(material_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE materials SET is_active = NOT is_active WHERE id = %s RETURNING is_active;",
        (material_id,)
    )
    updated = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": material_id, "is_active": updated[0]})

@app.route("/api/materials/<int:material_id>", methods=["DELETE"])
def delete_material(material_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM materials WHERE id = %s;", (material_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"deleted": True})



# 半完成品マスタ
@app.route("/api/semi_products", methods=["POST"])
def add_semi_product():
    data = request.json
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO semi_products (label_material_id, bag_material_id, threshold, replenish_quantity, is_active)
    VALUES (%s, %s, %s, %s, TRUE) RETURNING id;
""", (
    data["label_material_id"],
    data["bag_material_id"],
    data["threshold"],
    data["replenish_quantity"]
))
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201

@app.route("/api/semi_products", methods=["GET"])
def get_semi_products():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT sp.id, m1.name, m2.name, sp.threshold, sp.replenish_quantity, sp.is_active
        FROM semi_products sp
        JOIN materials m1 ON sp.label_material_id = m1.id
        JOIN materials m2 ON sp.bag_material_id = m2.id
        ORDER BY sp.created_at;
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([
        {
            "id": r[0],
            "label": r[1],
            "bag": r[2],
            "threshold": r[3],
            "replenish_quantity": r[4],
            "is_active": r[5]  # ← 忘れず返す！
        } for r in rows
    ])

@app.route("/api/semi_products/<int:semi_id>", methods=["PATCH"])
def update_semi_product(semi_id):
    data = request.json
    threshold = data.get("threshold")
    replenish = data.get("replenish_quantity")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE semi_products
        SET threshold = %s, replenish_quantity = %s
        WHERE id = %s
    """, (threshold, replenish, semi_id))
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"message": "更新しました！"})

@app.route("/api/auto_schedule_check", methods=["POST"])
def auto_add_work_schedules():
    conn = get_connection()
    cur = conn.cursor()

    # 閾値を下回ってる半完成品を抽出
    cur.execute("""
        SELECT s.id, s.threshold, s.replenish_quantity, COALESCE(i.stock, 0)
        FROM semi_products s
        LEFT JOIN inventory i ON i.semi_product_id = s.id
        WHERE s.is_active = TRUE AND COALESCE(i.stock, 0) <= s.threshold
    """)
    results = cur.fetchall()

    added = []
    for semi_id, threshold, replenish, stock in results:
        # 追加条件：replenish_quantity が 1 以上
        if replenish is None or replenish <= 0:
            continue

        # 既に「完了していない」作業予定があればスキップ
        cur.execute("""
            SELECT COUNT(*) FROM work_schedules
            WHERE product_type = 'semi' AND product_id = %s AND status != '完了'
        """, (semi_id,))
        exists = cur.fetchone()[0]

        if exists == 0:
            cur.execute("""
                INSERT INTO work_schedules (product_type, product_id, quantity, comment)
                VALUES ('semi', %s, %s, '自動追加（在庫が閾値以下）')
            """, (semi_id, replenish))
            added.append(semi_id)

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "added_count": len(added),
        "added_ids": added,
        "message": f"{len(added)} 件の作業予定を自動追加しました！"
    })




# 無効化 / 有効化の切り替え
@app.route("/api/semi_products/<int:semi_id>/toggle", methods=["PATCH"])
def toggle_semi_product(semi_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE semi_products SET is_active = NOT is_active WHERE id = %s RETURNING is_active;", (semi_id,))
    updated = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": semi_id, "is_active": updated[0]})

# 完全削除
@app.route("/api/semi_products/<int:semi_id>", methods=["DELETE"])
def delete_semi_product(semi_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM semi_products WHERE id = %s;", (semi_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"deleted": True})

# 完成品マスタ 登録
@app.route("/api/finished_products", methods=["POST"])
def add_finished_product():
    data = request.json
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO finished_products
    (destination, product_name, size, origin, seal_material_id, semi_product_id, is_active)
    VALUES (%s, %s, %s, %s, %s, %s, TRUE) RETURNING id;
""", (
    data["destination"],
    data["product_name"],
    data["size"],
    data["origin"],
    data["seal_material_id"],
    data["semi_product_id"]
))

    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201

# 完成品マスタ 一覧取得
@app.route("/api/finished_products", methods=["GET"])
def get_finished_products():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT fp.id, fp.destination, fp.product_name, fp.size, fp.origin,
           m.name AS seal_name,
           sm1.name AS label_name,
           sm2.name AS bag_name,
           fp.is_active,
           fp.created_at
    FROM finished_products fp
    JOIN materials m ON fp.seal_material_id = m.id
    JOIN semi_products sp ON fp.semi_product_id = sp.id
    JOIN materials sm1 ON sp.label_material_id = sm1.id
    JOIN materials sm2 ON sp.bag_material_id = sm2.id
    ORDER BY fp.created_at;
""")


    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([
    {
        "id": r[0],
        "destination": r[1],
        "product_name": r[2],
        "size": r[3],
        "origin": r[4],
        "seal_name": r[5],
        "label_name": r[6],
        "bag_name": r[7],
        "is_active": r[8],
        "created_at": r[9].strftime("%Y-%m-%d")  # ← ここで整形
    } for r in rows
])



# 無効化 / 有効化
@app.route("/api/finished_products/<int:product_id>/toggle", methods=["PATCH"])
def toggle_finished_product(product_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE finished_products SET is_active = NOT is_active WHERE id = %s RETURNING is_active;", (product_id,))
    updated = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": product_id, "is_active": updated[0]})

# 削除
@app.route("/api/finished_products/<int:product_id>", methods=["DELETE"])
def delete_finished_product(product_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM finished_products WHERE id = %s;", (product_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"deleted": True})

# 作業者マスタ関係
@app.route("/api/workers", methods=["GET"])
def get_workers():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, is_active, created_at
        FROM workers
        ORDER BY created_at;
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([
        {
            "id": r[0],
            "name": r[1],
            "is_active": r[2],
            "created_at": r[3].strftime("%Y-%m-%d")
        } for r in rows
    ])

@app.route("/api/workers", methods=["POST"])
def add_worker():
    data = request.json
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO workers (name, is_active) VALUES (%s, TRUE) RETURNING id;",
        (data["name"],)
    )
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201

@app.route("/api/workers/<int:worker_id>/toggle", methods=["PATCH"])
def toggle_worker(worker_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE workers SET is_active = NOT is_active WHERE id = %s RETURNING is_active;", (worker_id,))
    updated = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": worker_id, "is_active": updated[0]})

@app.route("/api/workers/<int:worker_id>", methods=["DELETE"])
def delete_worker(worker_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM workers WHERE id = %s;", (worker_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"deleted": True})

# 作業予定！
@app.route("/api/schedules", methods=["GET"])
def get_schedules():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT ws.id, ws.product_type, ws.product_id, w.id, w.name, ws.quantity, ws.jan_code, ws.comment, ws.status,
               CASE 
                 WHEN ws.product_type = 'semi' THEN
                   (SELECT CONCAT(m1.name, ' + ', m2.name)
                    FROM semi_products sp
                    JOIN materials m1 ON sp.label_material_id = m1.id
                    JOIN materials m2 ON sp.bag_material_id = m2.id
                    WHERE sp.id = ws.product_id)
                 WHEN ws.product_type = 'finished' THEN
                   (SELECT CONCAT(fp.destination, ' ', fp.product_name, ' ', fp.size, '（', fp.origin, '）')
                    FROM finished_products fp
                    WHERE fp.id = ws.product_id)
                 ELSE NULL
               END AS product_name
        FROM work_schedules ws
        LEFT JOIN workers w ON ws.worker_id = w.id
        WHERE ws.status IN ('予定', '依頼済')
        ORDER BY ws.created_at DESC;
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([
        {
            "id": r[0],
            "product_type": r[1],
            "product_id": r[2],
            "worker_id": r[3],
            "worker_name": r[4] or "（未入力）",
            "quantity": r[5],
            "jan_code": r[6],  # ← ★ これ追加！
            "comment": r[7],
            "status": r[8],
            "product_name": r[9] or f"ID:{r[2]}"
        } for r in rows
    ])

@app.route("/api/schedules", methods=["POST"])
def add_work_schedule():
    data = request.json
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO work_schedules
    (product_type, product_id, worker_id, quantity, jan_code, comment, status)
    VALUES (%s, %s, %s, %s, %s, %s, '予定')
    RETURNING id;
""", (
    data["product_type"],
    data["product_id"],
    data.get("worker_id"),
    data["quantity"],
    data.get("jan_code"),
    data.get("comment", "")
))
    new_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"id": new_id}), 201

@app.route("/api/schedules/<int:schedule_id>", methods=["DELETE"])
def delete_work_schedule(schedule_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM work_schedules WHERE id = %s;", (schedule_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"deleted": True})

@app.route("/api/schedules/<int:schedule_id>", methods=["PATCH"])
def update_schedule(schedule_id):
    data = request.json
    jan_code = data.get("jan_code")
    quantity = data.get("quantity")
    worker_id = data.get("worker_id")
    status = data.get("status")  # ← 追加されたstatusにも対応！

    conn = get_connection()
    cur = conn.cursor()

    # 更新するフィールドを動的に構築
    update_fields = []
    values = []

    if jan_code is not None:
        update_fields.append("jan_code = %s")
        values.append(jan_code)
    if quantity is not None:
        update_fields.append("quantity = %s")
        values.append(quantity)
    if worker_id is not None:
        update_fields.append("worker_id = %s")
        values.append(worker_id)
    if status is not None:
        update_fields.append("status = %s")
        values.append(status)

    if not update_fields:
        return jsonify({"error": "更新内容がありません"}), 400

    # 最後に WHERE 条件
    values.append(schedule_id)
    sql = f"UPDATE work_schedules SET {', '.join(update_fields)} WHERE id = %s;"
    cur.execute(sql, values)

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"message": "作業予定を更新しました"})

@app.route("/api/schedules/<int:schedule_id>/complete", methods=["PATCH"])
def complete_work_schedule(schedule_id):
    conn = get_connection()
    cur = conn.cursor()

    # 作業予定を取得
    cur.execute("SELECT product_type, product_id, quantity FROM work_schedules WHERE id = %s;", (schedule_id,))
    result = cur.fetchone()
    if not result:
        return jsonify({"error": "作業予定が見つかりません"}), 404

    product_type, product_id, quantity = result

    try:
        update_inventory_by_schedule(product_type, product_id, quantity, cur)
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

    # ステータス更新 & 完了日時
    cur.execute("""
        UPDATE work_schedules
        SET status = '完了', completed_at = CURRENT_TIMESTAMP
        WHERE id = %s;
    """, (schedule_id,))

    # ✅ 作業ログに登録（← これが必要やった！）
    cur.execute("""
        INSERT INTO work_logs (schedule_id, product_type, product_id, worker_id, quantity, comment)
        SELECT id, product_type, product_id, worker_id, quantity, comment
        FROM work_schedules
        WHERE id = %s;
    """, (schedule_id,))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"completed": True})


def update_inventory_by_schedule(product_type, product_id, quantity, cur):
    if product_type == "semi":
        cur.execute("SELECT label_material_id, bag_material_id FROM semi_products WHERE id = %s;", (product_id,))
        semi = cur.fetchone()
        if not semi:
            raise Exception("半完成品が見つかりません")
        label_id, bag_id = semi

        upsert_inventory_stock(cur, "material_id", label_id, -quantity)
        upsert_inventory_stock(cur, "material_id", bag_id, -quantity)
        upsert_inventory_stock(cur, "semi_product_id", product_id, quantity)

    elif product_type == "finished":
        cur.execute("SELECT semi_product_id, seal_material_id FROM finished_products WHERE id = %s;", (product_id,))
        result = cur.fetchone()
        if not result:
            raise Exception("完成品が見つかりません")
        semi_product_id, seal_material_id = result

        # 半完成品マイナス
        upsert_inventory_stock(cur, "semi_product_id", semi_product_id, -quantity)

        # 完成品プラス
        upsert_inventory_stock(cur, "finished_product_id", product_id, quantity)

        # 裏シールマイナス
        if seal_material_id:
            upsert_inventory_stock(cur, "material_id", seal_material_id, -quantity)



def upsert_inventory_stock(cur, column_name, item_id, delta):
    other_columns = {
        "material_id": ["semi_product_id", "finished_product_id"],
        "semi_product_id": ["material_id", "finished_product_id"],
        "finished_product_id": ["material_id", "semi_product_id"],
    }

    # WHERE句の構築
    where_clause = f"{column_name} = %s"
    for other_col in other_columns[column_name]:
        where_clause += f" AND {other_col} IS NULL"

    # 存在チェック
    cur.execute(f"SELECT id FROM inventory WHERE {where_clause}", (item_id,))
    result = cur.fetchone()

    if result:
        cur.execute(
            f"UPDATE inventory SET stock = stock + %s WHERE {where_clause}",
            (delta, item_id)
        )
    else:
        cur.execute(
            f"INSERT INTO inventory ({column_name}, stock) VALUES (%s, %s)",
            (item_id, delta)
        )

@app.route("/print_request")
def print_request():
    schedule_id = request.args.get("id", type=int)
    if not schedule_id:
        return "作業IDが指定されていません", 400

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT ws.product_type, ws.product_id, ws.quantity, ws.jan_code,
               fp.destination, fp.product_name, fp.size, fp.origin,
               m1.name AS label_name, m2.name AS bag_name, m3.name AS back_label_name
        FROM work_schedules ws
        LEFT JOIN finished_products fp ON ws.product_type = 'finished' AND ws.product_id = fp.id
        LEFT JOIN semi_products sp ON (
            (ws.product_type = 'semi' AND ws.product_id = sp.id) OR
            (ws.product_type = 'finished' AND fp.semi_product_id = sp.id)
        )
        LEFT JOIN materials m1 ON sp.label_material_id = m1.id
        LEFT JOIN materials m2 ON sp.bag_material_id = m2.id
        LEFT JOIN materials m3 ON fp.seal_material_id = m3.id
        WHERE ws.id = %s
    """, (schedule_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return "作業データが見つかりません", 404

    product_type = row[0]
    quantity = row[2]
    jan_code = row[3] or "JAN未登録"

    if product_type == "semi":
        label_name, bag_name = row[8], row[9]
        product_name = f"{label_name} + {bag_name}"
        packaging = f"{label_name}・{bag_name}"

    else:
        destination, name, size, origin = row[4], row[5], row[6], row[7]
        label_name, bag_name = row[8], row[9]
        product_name = f"{destination} {name} {size}（{origin}）"
        packaging = f"{label_name} + {bag_name}（JAN下6桁: {jan_code}）"

    return render_template("print_request.html",
                           schedule_id=schedule_id,
                           task_type="半完成品" if product_type == "semi" else "完成品",
                           product_name=product_name,
                           packaging=packaging,
                           back_label_name=row[10],
                           quantity=quantity,
                           print_date=datetime.datetime.now().strftime("%Y-%m-%d"))


# 作業ログ
@app.route("/api/work_logs", methods=["GET"])
def get_work_logs():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT wl.id, wl.product_type, wl.product_id, w.name, wl.quantity, wl.comment, wl.completed_at,
               CASE 
                 WHEN wl.product_type = 'semi' THEN
                   (SELECT CONCAT(m1.name, ' + ', m2.name)
                    FROM semi_products sp
                    JOIN materials m1 ON sp.label_material_id = m1.id
                    JOIN materials m2 ON sp.bag_material_id = m2.id
                    WHERE sp.id = wl.product_id)
                 WHEN wl.product_type = 'finished' THEN
                   (SELECT CONCAT(fp.destination, ' ', fp.product_name, ' ', fp.size, '（', fp.origin, '）')
                    FROM finished_products fp
                    WHERE fp.id = wl.product_id)
                 ELSE NULL
               END AS product_name
        FROM work_logs wl
        LEFT JOIN workers w ON wl.worker_id = w.id
        ORDER BY wl.completed_at DESC;
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([
    {
        "id": r[0],
        "product_type": r[1],
        "product_id": r[2],
        "worker_name": r[3] or "―",
        "quantity": r[4],
        "comment": r[5],
        "completed_at": (r[6] + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M"),
        "product_name": r[7] or f"ID:{r[2]}"
    } for r in rows
])


# 在庫一覧ページ
@app.route("/api/inventory", methods=["GET"])
def get_inventory():
    conn = get_connection()
    cur = conn.cursor()

    # 包材（在庫0でも表示、type付き）
    cur.execute("""
        SELECT m.id, m.name, m.type, i.id AS inventory_id, COALESCE(i.stock, 0)
        FROM materials m
        LEFT JOIN inventory i ON i.material_id = m.id
        WHERE m.is_active = TRUE
        ORDER BY m.type, m.id
    """)
    material_data = [
        {
             "id": r[0],
             "name": r[1],
             "type": r[2],
             "inventory_id": r[3],        # ← 追加：在庫テーブルのid
             "category": "material",
             "stock": r[4],
             "threshold": 100
        } for r in cur.fetchall()
    ]

    # 半完成品（在庫があるやつだけ）
    cur.execute("""
        SELECT sp.id, l.name AS label_name, b.name AS bag_name,
               i.id AS inventory_id, COALESCE(i.stock, 0)
        FROM semi_products sp
        JOIN materials l ON sp.label_material_id = l.id
        JOIN materials b ON sp.bag_material_id = b.id
        LEFT JOIN inventory i ON i.semi_product_id = sp.id
        WHERE sp.is_active = TRUE
        ORDER BY sp.id
    """)
    semi_data = [
        {
            "id": r[0],
            "name": f"{r[1]} × {r[2]}",       # ← ★ここで「品名」生成
            "inventory_id": r[3],
            "stock": r[4],
            "category": "semi"
        } for r in cur.fetchall()
    ]



     # 完成品（出荷先 / 商品名 / サイズ / 産地）
    cur.execute("""
        SELECT fp.id, fp.destination, fp.product_name, fp.size, fp.origin,
               i.id AS inventory_id, COALESCE(i.stock, 0)
        FROM finished_products fp
        LEFT JOIN inventory i ON i.finished_product_id = fp.id
        WHERE fp.is_active = TRUE
        ORDER BY fp.id
    """)
    finished_data = [
        {
            "id": r[0],
            "name": f"{r[1]} / {r[2]} / {r[3]} / {r[4]}",
            "inventory_id": r[5],
            "stock": r[6],
            "category": "finished"
        } for r in cur.fetchall()
    ]

    cur.close()
    conn.close()


    return jsonify(material_data + semi_data + finished_data)

@app.route("/api/inventory/adjust", methods=["POST"])
def adjust_inventory():
    data = request.json
    item_id = data["id"]
    category = data["category"]
    change = int(data["change"])
    comment = data.get("comment", "")

    column = {
        "material": "material_id",
        "semi": "semi_product_id",
        "finished": "finished_product_id"
    }.get(category)

    if not column:
        return jsonify({"error": "カテゴリが不正です"}), 400

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(f"SELECT stock FROM inventory WHERE {column} = %s", (item_id,))
    before = cur.fetchone()

    if before:
        cur.execute(f"""
            UPDATE inventory
            SET stock = stock + %s
            WHERE {column} = %s
        """, (change, item_id))
    else:
        # 存在しなければ新規作成
        cur.execute(f"""
            INSERT INTO inventory ({column}, stock)
            VALUES (%s, %s)
        """, (item_id, change))
        before = (0,)

    # ✅ 入荷ログ記録（包材のみ）
    if category == "material" and change > 0:
        cur.execute("""
            INSERT INTO material_arrival_logs (material_id, quantity, comment)
            VALUES (%s, %s, %s)
        """, (item_id, change, comment))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"message": f"在庫更新成功！変更前: {before[0]} → 変更後: {before[0] + change}"})

@app.route("/api/material_arrival_logs")
def get_material_arrival_logs():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT l.id, m.name, l.quantity, l.comment, l.arrived_at
        FROM material_arrival_logs l
        JOIN materials m ON l.material_id = m.id
        ORDER BY l.arrived_at DESC
    """)

    logs = [
        {
            "id": row[0],
            "material_name": row[1],
            "quantity": row[2],
            "comment": row[3],
            "arrived_at": row[4].isoformat()  # JavaScriptで扱いやすくするためISO形式に
        } for row in cur.fetchall()
    ]

    cur.close()
    conn.close()
    return jsonify(logs)


# 蔵出しページ
# 完成品のみの在庫取得API
@app.route("/api/dispatch", methods=["GET"])
def get_dispatch_items():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT i.id, fp.destination, fp.product_name, fp.size, fp.origin, i.stock
        FROM inventory i
        JOIN finished_products fp ON i.finished_product_id = fp.id
        WHERE i.stock > 0
        ORDER BY i.id;
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([
        {
            "inventory_id": r[0],
            "name": f"{r[1]} {r[2]} {r[3]}（{r[4]}）",
            "stock": r[5]
        } for r in rows
    ])

# 在庫マイナス（蔵出し）
@app.route("/api/inventory/<int:inventory_id>/use", methods=["PATCH"])
def use_inventory(inventory_id):
    data = request.json
    quantity = data.get("quantity", 0)
    comment = data.get("comment", "")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("UPDATE inventory SET stock = stock - %s WHERE id = %s AND stock >= %s;",
                (quantity, inventory_id, quantity))

    # 在庫テーブルから完成品IDを取得
    cur.execute("SELECT finished_product_id FROM inventory WHERE id = %s", (inventory_id,))
    product_id = cur.fetchone()[0]

    # use_inventory, restore_inventory 内の INSERT 文
    cur.execute("""
    INSERT INTO dispatch_logs (product_id, quantity, comment)
    VALUES (%s, %s, %s)
""", (product_id, quantity, comment))



    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "ok"})


# 在庫プラス（戻し）
@app.route("/api/inventory/<int:inventory_id>/restore", methods=["PATCH"])
def restore_inventory(inventory_id):
    data = request.json
    quantity = data.get("quantity", 0)
    comment = data.get("comment", "")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("UPDATE inventory SET stock = stock + %s WHERE id = %s;",
                (quantity, inventory_id))

    # 在庫テーブルから完成品IDを取得
    cur.execute("SELECT finished_product_id FROM inventory WHERE id = %s", (inventory_id,))
    product_id = cur.fetchone()[0]

    # use_inventory, restore_inventory 内の INSERT 文
    cur.execute("""
    INSERT INTO dispatch_logs (product_id, quantity, comment)
    VALUES (%s, %s, %s)
""", (product_id, quantity, comment))




    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "ok"})

# 棚卸
@app.route("/api/stock_adjust_logs", methods=["GET"])
def get_stock_adjust_logs():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            l.id,
            i.id AS inventory_id,
            i.material_id,
            COALESCE(m.name, '') AS material_name,
            i.semi_product_id,
            COALESCE(label.name || ' × ' || bag.name, '') AS semi_name,
            i.finished_product_id,
            COALESCE(fp.destination, '') AS dest,
            COALESCE(fp.product_name, '') AS fname,
            COALESCE(fp.size, '') AS fsize,
            COALESCE(fp.origin, '') AS forigin,
            l.before_stock,
            l.after_stock,
            l.comment,
            l.item_type,
            l.created_at
        FROM stock_adjust_logs l
        JOIN inventory i ON l.inventory_id = i.id
        LEFT JOIN materials m ON i.material_id = m.id
        LEFT JOIN semi_products sp ON i.semi_product_id = sp.id
        LEFT JOIN materials label ON sp.label_material_id = label.id
        LEFT JOIN materials bag ON sp.bag_material_id = bag.id
        LEFT JOIN finished_products fp ON i.finished_product_id = fp.id
        ORDER BY l.created_at DESC
        LIMIT 100
    """)

    rows = cur.fetchall()
    logs = []

    for row in rows:
        material_id = row[2]
        material_name = row[3]
        semi_id = row[4]
        semi_name = row[5]
        finished_id = row[6]
        dest = row[7]
        fname = row[8]
        fsize = row[9]
        forigin = row[10]
        before = row[11]
        after = row[12]
        comment = row[13]
        item_type = row[14]
        created_at = row[15]

        # 🧠 カテゴリに応じて名称を正しく抽出
        if item_type == "material":
            category = "包材"
            item = material_name or f"ID: {material_id}"
        elif item_type == "semi":
            category = "半完成品"
            item = semi_name or f"ID: {semi_id}"
        elif item_type == "finished":
            category = "完成品"
            item = f"{dest} / {fname} / {fsize} / {forigin}" if fname else f"ID: {finished_id}"
        else:
            category = "不明"
            item = "不明"

        logs.append({
            "id": row[0],
            "item": item,
            "category": category,
            "before": before,
            "after": after,
            "comment": comment,
            "date": created_at.isoformat()
        })

    cur.close()
    conn.close()
    return jsonify(logs)



# 棚卸しによる在庫更新
@app.route("/api/stock_adjust", methods=["POST"])
def adjust_stock_actual():
    data = request.json
    inventory_id = data.get("id")  # inventory.id（在庫テーブルの主キー）
    actual_stock = int(data.get("actual_stock", 0))
    comment = data.get("comment", "")
    category = data.get("category")  # material / semi / finished

    print("📦 inventory_id:", inventory_id)
    print("📦 actual_stock:", actual_stock)
    print("📦 category:", category)

    conn = get_connection()
    cur = conn.cursor()

    # 現在の在庫を取得
    cur.execute("SELECT stock FROM inventory WHERE id = %s", (inventory_id,))
    result = cur.fetchone()
    if not result:
        print("❌ 在庫が見つかりません")
        return jsonify({"error": "在庫が見つかりません"}), 404

    current_stock = result[0]
    diff = actual_stock - current_stock
    print("📊 現在:", current_stock, "→", actual_stock, "（差分:", diff, "）")

    # 在庫を実数に上書き
    cur.execute("UPDATE inventory SET stock = %s WHERE id = %s", (actual_stock, inventory_id))

    # ログ記録（item_type を含む！）
    cur.execute("""
        INSERT INTO stock_adjust_logs (inventory_id, item_type, before_stock, after_stock, comment)
        VALUES (%s, %s, %s, %s, %s)
    """, (inventory_id, category, current_stock, actual_stock, comment))

    conn.commit()
    cur.close()
    conn.close()

    print("✅ 棚卸し完了、ログ記録OK")

    return jsonify({
        "message": "在庫を調整しました",
        "inventory_id": inventory_id,
        "before": current_stock,
        "after": actual_stock,
        "diff": diff
    })


@app.route("/api/materials/category/<category>", methods=["GET"])
def get_materials_by_category(category):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name 
        FROM materials 
        WHERE type = %s AND is_active = TRUE
        ORDER BY name;
    """, (category,))
    
    materials = [{"id": row[0], "name": row[1]} for row in cur.fetchall()]

    cur.close()
    conn.close()

    return jsonify(materials)




@app.route("/inventory")
def inventory():
    return render_template("inventory.html")

@app.route("/work_schedule")
def work_schedule():
    return render_template("work_schedule.html")

@app.route("/work_log")
def work_log():
    return render_template("work_log.html")

@app.route("/master_material")
def master_material():
    return render_template("master_material.html")

@app.route("/master_semi")
def master_semi():
    return render_template("master_semi.html")

@app.route("/master_finished")
def master_finished():
    return render_template("master_finished.html")

@app.route("/master_worker")
def master_worker():
    return render_template("master_worker.html")

@app.route("/shipment")
def shipment():
    return render_template("shipment.html")

@app.route("/dispatch")
def dispatch():
    return render_template("dispatch.html")

@app.route("/stock_adjust")
def stock_adjust():
    return render_template("stock_adjust.html")

@app.route("/stock_adjust_logs")
def stock_adjust_logs_page():
    return render_template("stock_adjust_logs.html")

@app.route("/arrival")
def arrival():
    return render_template("arrival.html")

@app.route("/arrival_logs")
def arrival_logs_page():
    return render_template("arrival_logs.html")

@app.route("/setting_logs")
def setting_logs_page():
    return render_template("setting_logs.html")








if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
