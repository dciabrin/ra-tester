define finish_and_kill
finish
kill
quit
end

set pagination off
set confirm off
set breakpoint pending on

# mariadb 5.5
b trx_prepare_off_kernel
commands
silent
finish_and_kill
end

# mariadb 10.1
b trx_prepare
commands
silent
finish_and_kill
end

continue
