-- 查询大额订单明细。现有 idx_user_id 无法按金额过滤，组合索引效果以影子库实测为准。
SELECT id, amount, created_at
FROM orders
WHERE user_id = 42 AND amount > 500;

-- 查询用户的已支付订单。组合索引是否有收益以影子库实测为准。
SELECT COUNT(*), SUM(amount)
FROM orders
WHERE user_id = 42 AND status = 1;
