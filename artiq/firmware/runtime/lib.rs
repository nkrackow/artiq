#![no_std]
#![feature(compiler_builtins_lib, alloc, repr_simd, lang_items, const_fn, global_allocator)]

extern crate compiler_builtins;
extern crate alloc;
extern crate cslice;
#[macro_use]
extern crate log;
extern crate byteorder;
extern crate fringe;
extern crate smoltcp;

extern crate alloc_list;
#[macro_use]
extern crate std_artiq as std;
extern crate logger_artiq;
extern crate backtrace_artiq;
#[macro_use]
extern crate board;
extern crate proto;
extern crate amp;
#[cfg(has_drtio)]
extern crate drtioaux;

use smoltcp::wire::{EthernetAddress, IpAddress, IpCidr};

use board::config;
use proto::{mgmt_proto, analyzer_proto, moninj_proto, rpc_proto, session_proto, kernel_proto};
use amp::{mailbox, rpc_queue};

mod ethmac;
mod rtio_mgt;

mod urc;
mod sched;
mod cache;
mod rtio_dma;

mod mgmt;
mod kernel;
mod kern_hwreq;
mod session;
#[cfg(any(has_rtio_moninj, has_drtio))]
mod moninj;
#[cfg(has_rtio_analyzer)]
mod analyzer;

fn startup() {
    board::clock::init();
    info!("ARTIQ runtime starting...");
    info!("software version {}", include_str!(concat!(env!("OUT_DIR"), "/git-describe")));
    info!("gateware version {}", board::ident(&mut [0; 64]));

    let t = board::clock::get_ms();
    info!("press 'e' to erase startup and idle kernels...");
    while board::clock::get_ms() < t + 1000 {
        if unsafe { board::csr::uart::rxtx_read() == b'e' } {
            config::remove("startup_kernel").unwrap();
            config::remove("idle_kernel").unwrap();
            info!("startup and idle kernels erased");
            break
        }
    }
    info!("continuing boot");

    #[cfg(has_i2c)]
    board::i2c::init();
    #[cfg(has_ad9516)]
    board::ad9516::init().expect("cannot initialize ad9516");
    #[cfg(has_ad9154)]
    board::ad9154::init().expect("cannot initialize ad9154");

    let hardware_addr;
    match config::read_str("mac", |r| r?.parse()) {
        Err(()) => {
            hardware_addr = EthernetAddress([0x02, 0x00, 0x00, 0x00, 0x00, 0x01]);
            warn!("using default MAC address {}; consider changing it", hardware_addr);
        }
        Ok(addr) => {
            hardware_addr = addr;
            info!("using MAC address {}", hardware_addr);
        }
    }

    let protocol_addr;
    match config::read_str("ip", |r| r?.parse()) {
        Err(()) => {
            protocol_addr = IpAddress::v4(192, 168, 1, 50);
            info!("using default IP address {}", protocol_addr);
        }
        Ok(addr) => {
            protocol_addr = addr;
            info!("using IP address {}", protocol_addr);
        }
    }

    let net_device = unsafe { ethmac::EthernetDevice::new() };

    let net_device = {
        use smoltcp::wire::PrettyPrinter;
        use smoltcp::wire::EthernetFrame;

        fn net_trace_writer(timestamp: u64, printer: PrettyPrinter<EthernetFrame<&[u8]>>) {
            let seconds = timestamp / 1000;
            let micros  = timestamp % 1000 * 1000;
            print!("\x1b[37m[{:6}.{:06}s]\n{}\x1b[0m\n", seconds, micros, printer)
        }

        fn net_trace_silent(_timestamp: u64, _printer: PrettyPrinter<EthernetFrame<&[u8]>>) {}

        let net_trace_fn: fn(u64, PrettyPrinter<EthernetFrame<&[u8]>>);
        match config::read_str("net_trace", |r| r.map(|s| s == "1")) {
            Ok(true) => net_trace_fn = net_trace_writer,
            _ => net_trace_fn = net_trace_silent
        }
        smoltcp::phy::EthernetTracer::new(net_device, net_trace_fn)
    };

    let mut neighbor_cache_storage = [None; 8];
    let neighbor_cache =
        smoltcp::iface::NeighborCache::new(&mut neighbor_cache_storage[..]);
    let mut interface  =
        smoltcp::iface::EthernetInterfaceBuilder::new(net_device)
                       .neighbor_cache(neighbor_cache)
                       .ethernet_addr(hardware_addr)
                       .ip_addrs([IpCidr::new(protocol_addr, 0)])
                       .finalize();

    let mut scheduler = sched::Scheduler::new();
    let io = scheduler.io();
    rtio_mgt::startup(&io);
    io.spawn(4096, mgmt::thread);
    io.spawn(16384, session::thread);
    #[cfg(any(has_rtio_moninj, has_drtio))]
    io.spawn(4096, moninj::thread);
    #[cfg(has_rtio_analyzer)]
    io.spawn(4096, analyzer::thread);

    match config::read_str("log_level", |r| r?.parse()) {
        Err(()) => (),
        Ok(log_level_filter) => {
            info!("log level set to {} by `log_level` config key",
                  log_level_filter);
            logger_artiq::BufferLogger::with(|logger|
                logger.set_max_log_level(log_level_filter));
        }
    }

    match config::read_str("uart_log_level", |r| r?.parse()) {
        Err(()) => {
            info!("UART log level set to INFO by default");
        },
        Ok(uart_log_level_filter) => {
            info!("UART log level set to {} by `uart_log_level` config key",
                  uart_log_level_filter);
            logger_artiq::BufferLogger::with(|logger|
                logger.set_uart_log_level(uart_log_level_filter));
        }
    }

    loop {
        scheduler.run();

        {
            let sockets = &mut *scheduler.sockets().borrow_mut();
            loop {
                match interface.poll(sockets, board::clock::get_ms()) {
                    Ok(true) => (),
                    Ok(false) => break,
                    Err(smoltcp::Error::Unrecognized) => (),
                    Err(err) => warn!("network error: {}", err)
                }
            }
        }
    }
}

#[global_allocator]
static mut ALLOC: alloc_list::ListAlloc = alloc_list::EMPTY;
static mut LOG_BUFFER: [u8; 1<<17] = [0; 1<<17];

#[no_mangle]
pub extern fn main() -> i32 {
    unsafe {
        extern {
            static mut _fheap: u8;
            static mut _eheap: u8;
        }
        ALLOC.add_range(&mut _fheap, &mut _eheap);

        logger_artiq::BufferLogger::new(&mut LOG_BUFFER[..]).register(startup);

        0
    }
}

#[no_mangle]
pub extern fn exception_handler(vect: u32, _regs: *const u32, pc: u32, ea: u32) {
    panic!("exception {:?} at PC 0x{:x}, EA 0x{:x}", vect, pc, ea)
}

#[no_mangle]
pub extern fn abort() {
    println!("aborted");

    loop {}
}

#[no_mangle]
#[lang = "panic_fmt"]
pub extern fn panic_fmt(args: core::fmt::Arguments, file: &'static str, line: u32) -> ! {
    println!("panic at {}:{}: {}", file, line, args);

    println!("backtrace for software version {}:",
             include_str!(concat!(env!("OUT_DIR"), "/git-describe")));
    let _ = backtrace_artiq::backtrace(|ip| {
        println!("{:#08x}", ip);
    });

    if config::read_str("panic_reboot", |r| r == Ok("1")) {
        println!("rebooting...");
        unsafe { board::boot::reboot() }
    } else {
        println!("halting.");
        println!("use `artiq_coreconfig write -s panic_reboot 1` to reboot instead");
        loop {}
    }
}