-- 语句一:大额订单明细。amount 上无任何索引,现有 idx_user_id 只能定位到用户
-- 再逐行回表过滤——候选组合索引应显著降低代价(实测见 README)。
SELECT id, amount, created_at
FROM orders
WHERE user_id = 42 AND amount > 500;

-- 语句二:按用户统计已支付订单。教科书会建议 (user_id, status) 组合索引,
-- 但在本场景数据规模下未必真有收益——交给影子库实测裁决。
SELECT COUNT(*), SUM(amount)
FROM orders
WHERE user_id = 42 AND status = 1;
