ALTER USER 'admin'@'%' IDENTIFIED WITH mysql_native_password BY 'Sunny50030$$';
FLUSH PRIVILEGES;
SELECT user, host FROM mysql.user WHERE user='admin';

