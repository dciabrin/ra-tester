define finish_and_kill
finish
kill
quit
end

set pagination off
set confirm off
b trx_prepare_off_kernel
command 1
silent
finish_and_kill
end

