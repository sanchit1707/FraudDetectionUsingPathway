import psutil

def get_sys_load()->float:
    return psutil.cpu_percent(interval=0.1)/100 
